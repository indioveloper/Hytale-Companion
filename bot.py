"""
Hytale Wiki Bot - Bot de Discord para consultar la wiki de Hytale
Usa la API de MediaWiki de hytalewiki.org
"""

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from typing import Optional
from rapidfuzz import fuzz, process
import os

TOKEN = os.environ.get("DISCORD_TOKEN")
WIKI_BASE_URL = "https://hytalewiki.org"
WIKI_API_URL = "https://hytalewiki.org/api.php"


class WikiBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
    
    async def setup_hook(self):
        await self.tree.sync()
        print(f"Comandos sincronizados")

    async def on_ready(self):
        print(f"Bot conectado como {self.user}")
        print(f"En {len(self.guilds)} servidor(es)")


bot = WikiBot()


class WikiAPI:
    """Cliente para la API de MediaWiki"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.api_url = WIKI_API_URL
        self.base_url = WIKI_BASE_URL
    
    async def search(self, query: str, limit: int = 5) -> list[dict]:
        """Busca artículos en la wiki"""
        params = {
            "action": "opensearch",
            "search": query,
            "limit": str(limit),
            "namespace": "0",
            "format": "json"
        }
        
        async with self.session.get(self.api_url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                if len(data) >= 4:
                    titles = data[1]
                    descriptions = data[2]
                    urls = data[3]
                    return [
                        {"title": t, "description": d, "url": u}
                        for t, d, u in zip(titles, descriptions, urls)
                    ]
            return []
    
    async def search_full(self, query: str, limit: int = 20) -> list[dict]:
        """Búsqueda más amplia para fuzzy matching"""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": str(limit),
            "format": "json"
        }
        
        async with self.session.get(self.api_url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                results = data.get("query", {}).get("search", [])
                return [
                    {
                        "title": r.get("title"),
                        "description": r.get("snippet", "").replace('<span class="searchmatch">', '').replace('</span>', ''),
                        "url": f"{self.base_url}/w/{r.get('title').replace(' ', '_')}"
                    }
                    for r in results
                ]
            return []
    
    async def get_all_pages(self, prefix: str = "", limit: int = 50) -> list[str]:
        """Obtiene lista de páginas para fuzzy matching"""
        params = {
            "action": "query",
            "list": "allpages",
            "aplimit": str(limit),
            "apprefix": prefix[:2] if prefix else "",
            "format": "json"
        }
        
        async with self.session.get(self.api_url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                pages = data.get("query", {}).get("allpages", [])
                return [p.get("title") for p in pages]
            return []
    
    async def get_page_extract(self, title: str) -> Optional[dict]:
        """Obtiene el extracto de una página"""
        params = {
            "action": "query",
            "titles": title,
            "prop": "extracts|pageimages|info",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": "5",
            "piprop": "thumbnail",
            "pithumbsize": "300",
            "inprop": "url",
            "format": "json"
        }
        
        async with self.session.get(self.api_url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                pages = data.get("query", {}).get("pages", {})
                
                for page_id, page_data in pages.items():
                    if page_id == "-1":
                        return None
                    
                    return {
                        "title": page_data.get("title", title),
                        "extract": page_data.get("extract", "Sin descripción disponible."),
                        "url": page_data.get("fullurl", f"{self.base_url}/w/{title}"),
                        "thumbnail": page_data.get("thumbnail", {}).get("source")
                    }
        return None
    
    async def get_random_page(self) -> Optional[dict]:
        """Obtiene una página aleatoria"""
        params = {
            "action": "query",
            "list": "random",
            "rnnamespace": "0",
            "rnlimit": "1",
            "format": "json"
        }
        
        async with self.session.get(self.api_url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                random_pages = data.get("query", {}).get("random", [])
                if random_pages:
                    title = random_pages[0].get("title")
                    return await self.get_page_extract(title)
        return None
    
    async def get_categories(self, title: str) -> list[str]:
        """Obtiene las categorías de una página"""
        params = {
            "action": "query",
            "titles": title,
            "prop": "categories",
            "cllimit": "10",
            "format": "json"
        }
        
        async with self.session.get(self.api_url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                pages = data.get("query", {}).get("pages", {})
                
                for page_data in pages.values():
                    categories = page_data.get("categories", [])
                    return [
                        cat.get("title", "").replace("Category:", "")
                        for cat in categories
                    ]
        return []
    
    async def fuzzy_search(self, query: str, threshold: int = 60) -> list[dict]:
        """Búsqueda fuzzy - encuentra coincidencias aproximadas"""
        # Primero busca con la API normal
        results = await self.search(query, limit=10)
        
        # Si no hay resultados, busca páginas similares
        if not results:
            # Obtener páginas que empiecen con letras similares
            all_pages = await self.get_all_pages(query)
            
            if all_pages:
                # Usar rapidfuzz para encontrar las mejores coincidencias
                matches = process.extract(
                    query, 
                    all_pages, 
                    scorer=fuzz.WRatio,
                    limit=5
                )
                
                # Filtrar por threshold y convertir a formato estándar
                results = [
                    {
                        "title": match[0],
                        "description": f"Coincidencia: {match[1]}%",
                        "url": f"{self.base_url}/w/{match[0].replace(' ', '_')}",
                        "score": match[1]
                    }
                    for match in matches
                    if match[1] >= threshold
                ]
        
        # Si aún no hay resultados, búsqueda más amplia
        if not results:
            results = await self.search_full(query, limit=10)
            
            if results:
                # Aplicar fuzzy matching a los resultados
                titles = [r["title"] for r in results]
                matches = process.extract(
                    query,
                    titles,
                    scorer=fuzz.WRatio,
                    limit=5
                )
                
                # Reordenar resultados por score fuzzy
                scored_results = []
                for match in matches:
                    for r in results:
                        if r["title"] == match[0]:
                            r["score"] = match[1]
                            scored_results.append(r)
                            break
                
                results = scored_results
        
        return results


def create_wiki_embed(page_data: dict, categories: list[str] = None) -> discord.Embed:
    """Crea un embed con la información de la wiki"""
    embed = discord.Embed(
        title=page_data["title"],
        url=page_data["url"],
        description=page_data["extract"][:1000] + "..." if len(page_data["extract"]) > 1000 else page_data["extract"],
        color=0x00A8E8
    )
    
    if page_data.get("thumbnail"):
        embed.set_thumbnail(url=page_data["thumbnail"])
    
    if categories:
        embed.add_field(
            name="Categorías",
            value=", ".join(categories[:5]) or "Sin categorías",
            inline=False
        )
    
    embed.set_footer(text="HytaleWiki.org • Hytale Wiki Bot")
    
    return embed


def create_search_embed(results: list[dict], query: str, fuzzy: bool = False) -> discord.Embed:
    """Crea un embed con los resultados de búsqueda"""
    title = f"🔍 Resultados para: {query}"
    if fuzzy:
        title = f"🔎 ¿Quisiste decir...? ({query})"
    
    embed = discord.Embed(
        title=title,
        color=0x00A8E8
    )
    
    if not results:
        embed.description = "No se encontraron resultados."
    else:
        description_parts = []
        for i, result in enumerate(results, 1):
            title = result["title"]
            url = result["url"]
            score = result.get("score")
            
            if score:
                description_parts.append(f"**{i}. [{title}]({url})** ({score}% coincidencia)")
            else:
                desc = result.get("description", "")[:80]
                if desc:
                    desc = desc + "..." if len(result.get("description", "")) > 80 else desc
                description_parts.append(f"**{i}. [{title}]({url})**\n{desc or 'Sin descripción'}")
        
        embed.description = "\n\n".join(description_parts)
    
    embed.set_footer(text="HytaleWiki.org • Usa /wiki <artículo> para ver detalles")
    
    return embed


# ============== COMANDOS ==============

@bot.tree.command(name="wiki", description="Busca un artículo en la wiki de Hytale")
@app_commands.describe(articulo="Nombre del artículo a buscar")
async def wiki_command(interaction: discord.Interaction, articulo: str):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        wiki = WikiAPI(session)
        
        # Primero intenta obtener la página directamente
        page = await wiki.get_page_extract(articulo)
        
        if page:
            categories = await wiki.get_categories(articulo)
            embed = create_wiki_embed(page, categories)
            await interaction.followup.send(embed=embed)
        else:
            # Búsqueda fuzzy si no hay coincidencia exacta
            results = await wiki.fuzzy_search(articulo)
            
            if results:
                # Si hay una coincidencia muy alta (>85%), mostrarla directamente
                best_match = results[0]
                if best_match.get("score", 0) >= 85:
                    page = await wiki.get_page_extract(best_match["title"])
                    if page:
                        categories = await wiki.get_categories(best_match["title"])
                        embed = create_wiki_embed(page, categories)
                        await interaction.followup.send(embed=embed)
                        return
                
                # Si no, mostrar sugerencias
                embed = create_search_embed(results, articulo, fuzzy=True)
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    f"❌ No se encontró ningún artículo para **{articulo}**",
                    ephemeral=True
                )


@bot.tree.command(name="wikisearch", description="Busca artículos en la wiki de Hytale")
@app_commands.describe(busqueda="Términos de búsqueda")
async def wikisearch_command(interaction: discord.Interaction, busqueda: str):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        wiki = WikiAPI(session)
        results = await wiki.fuzzy_search(busqueda)
        embed = create_search_embed(results, busqueda, fuzzy=bool(results and results[0].get("score")))
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="wikirandom", description="Muestra un artículo aleatorio de la wiki")
async def wikirandom_command(interaction: discord.Interaction):
    await interaction.response.defer()
    
    async with aiohttp.ClientSession() as session:
        wiki = WikiAPI(session)
        page = await wiki.get_random_page()
        
        if page:
            categories = await wiki.get_categories(page["title"])
            embed = create_wiki_embed(page, categories)
            embed.title = f"🎲 {embed.title}"
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(
                "❌ No se pudo obtener un artículo aleatorio",
                ephemeral=True
            )


@bot.tree.command(name="wikihelp", description="Muestra ayuda sobre el bot de la wiki")
async def wikihelp_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 Hytale Wiki Bot - Ayuda",
        description="Bot para consultar la wiki de Hytale directamente desde Discord.",
        color=0x00A8E8
    )
    
    embed.add_field(
        name="/wiki <artículo>",
        value="Busca y muestra información de un artículo específico.\nIncluye búsqueda fuzzy para errores tipográficos.",
        inline=False
    )
    embed.add_field(
        name="/wikisearch <búsqueda>",
        value="Busca artículos relacionados con los términos indicados.",
        inline=False
    )
    embed.add_field(
        name="/wikirandom",
        value="Muestra un artículo aleatorio de la wiki.",
        inline=False
    )
    
    embed.add_field(
        name="📖 Wiki",
        value="[HytaleWiki.org](https://hytalewiki.org)",
        inline=True
    )
    embed.add_field(
        name="🎮 Hytale",
        value="[Hytale.com](https://hytale.com)",
        inline=True
    )
    
    embed.set_footer(text="Hytale Wiki Bot • Early Access: 13 Enero 2026")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="tiempo_restante", description="Muestra el tiempo restante hasta el lanzamiento de Hytale")
async def tiempo_restante_command(interaction: discord.Interaction):
    from datetime import datetime, timezone, timedelta
    
    # Fecha de lanzamiento: 13 de enero 2026, 17:00 CET (UTC+1)
    cet = timezone(timedelta(hours=1))
    launch_date = datetime(2026, 1, 13, 17, 0, 0, tzinfo=cet)
    
    now = datetime.now(cet)
    remaining = launch_date - now
    
    if remaining.total_seconds() <= 0:
        embed = discord.Embed(
            title="🚀 ¡HYTALE YA ESTÁ DISPONIBLE!",
            description="El Early Access ha comenzado. ¡A jugar!",
            color=0x00FF00,
            url="https://hytale.com"
        )
    else:
        days = remaining.days
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        embed = discord.Embed(
            title="⏳ Tiempo restante para Hytale Early Access",
            color=0x00A8E8
        )
        
        embed.add_field(name="📅 Días", value=f"**{days}**", inline=True)
        embed.add_field(name="🕐 Horas", value=f"**{hours}**", inline=True)
        embed.add_field(name="⏱️ Minutos", value=f"**{minutes}**", inline=True)
        
        embed.add_field(
            name="📆 Fecha de lanzamiento",
            value="13 de Enero de 2026 a las 17:00 CET",
            inline=False
        )
        
        embed.set_footer(text="hytale.com")
    
    await interaction.response.send_message(embed=embed)

# ============== MAIN ==============

if __name__ == "__main__":
    bot.run(TOKEN)
