import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime
from database import Database
from tracker import VoiceTracker
from stats import StatsFormatter

# ── Konfiguracja ─────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("COMMAND_PREFIX", "!")

# ID kanału głosowego śledzonego SPECJALNIE (Piątek+Sobota 20:00–02:00)
SPECIAL_CHANNEL_ID = int(os.getenv("SPECIAL_CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command("help")

db = Database()
tracker = VoiceTracker(db, SPECIAL_CHANNEL_ID)
fmt = StatsFormatter()

# ── Eventy ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅  Zalogowano jako {bot.user} ({bot.user.id})")
    print(f"📊  Baza danych: {db.db_url[:40]}...")
    await db.init()
    save_sessions.start()
    print("⏱️   Tracker uruchomiony.")

@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.utcnow()

    # Użytkownik dołączył do kanału
    if after.channel and (not before.channel or before.channel.id != after.channel.id):
        tracker.join(member.id, member.display_name, after.channel.id, after.channel.name, now)

    # Użytkownik opuścił kanał
    if before.channel and (not after.channel or before.channel.id != after.channel.id):
        await tracker.leave(member.id, before.channel.id, now)

# ── Zadanie cykliczne: zapisuj co 5 minut ────────────────────────────────────

@tasks.loop(minutes=5)
async def save_sessions():
    """Zapisuje trwające sesje co 5 minut (na wypadek restartu)."""
    await tracker.flush_active(datetime.utcnow())

# ── Komendy statystyk ─────────────────────────────────────────────────────────

@bot.command(name="czas-tydzien", aliases=["czas-tydzień"])
async def stats_week(ctx):
    rows = await db.get_stats(period="week")
    embed = fmt.build_embed(rows, "📅 Aktywność – ostatnie 7 dni", discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="czas-miesiac", aliases=["czas-miesiąc"])
async def stats_month(ctx):
    rows = await db.get_stats(period="month")
    embed = fmt.build_embed(rows, "📆 Aktywność – ostatnie 30 dni", discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name="czas-polrocze", aliases=["czas-półrocze"])
async def stats_halfyear(ctx):
    rows = await db.get_stats(period="halfyear")
    embed = fmt.build_embed(rows, "📊 Aktywność – ostatnie 6 miesięcy", discord.Color.orange())
    await ctx.send(embed=embed)

@bot.command(name="czas-alltime")
async def stats_alltime(ctx):
    rows = await db.get_stats(period="alltime")
    embed = fmt.build_embed(rows, "🏆 Aktywność – wszystkie czasy", discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name="czas-specjalny")
async def stats_special(ctx):
    """Statystyki tylko z wyróżnionego kanału (Pt+Sb 20–02)."""
    if SPECIAL_CHANNEL_ID == 0:
        await ctx.send("❌ Specjalny kanał nie jest skonfigurowany (`SPECIAL_CHANNEL_ID`).")
        return
    rows = await db.get_special_stats()
    embed = fmt.build_embed(rows, "🎉 Specjalny kanał – Pt/Sb 20:00–02:00 (all time)", discord.Color.purple())
    await ctx.send(embed=embed)

@bot.command(name="czas-kto")
async def stats_user(ctx, *, member: discord.Member = None):
    """!czas-kto [@użytkownik] – statystyki konkretnej osoby."""
    target = member or ctx.author
    rows = await db.get_user_stats(target.id)
    embed = fmt.build_user_embed(rows, target.display_name)
    await ctx.send(embed=embed)

@bot.command(name="czas-online")
async def stats_online(ctx):
    """Pokaż kto aktualnie siedzi na kanałach głosowych i jak długo."""
    now = datetime.utcnow()
    lines = []
    for uid, session in tracker.active.items():
        elapsed = now - session["joined"]
        h, rem = divmod(int(elapsed.total_seconds()), 3600)
        m = rem // 60
        name = session["display_name"]
        chan = session["channel_name"]
        special = " 🎉" if session.get("is_special") else ""
        lines.append(f"**{name}** – #{chan}{special} – `{h:02d}:{m:02d}`")

    if not lines:
        embed = discord.Embed(description="Nikt nie siedzi teraz na kanałach głosowych. 🔇",
                              color=discord.Color.greyple())
    else:
        embed = discord.Embed(title="🔊 Aktualnie na kanałach",
                              description="\n".join(lines),
                              color=discord.Color.teal())
    await ctx.send(embed=embed)

@bot.command(name="pomoc", aliases=["help"])
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Komendy bota", color=discord.Color.blurple())
    cmds = [
        ("!czas-tydzień", "Top aktywności z ostatnich 7 dni"),
        ("!czas-miesiąc", "Top aktywności z ostatnich 30 dni"),
        ("!czas-półrocze", "Top aktywności z ostatnich 6 miesięcy"),
        ("!czas-alltime", "Top aktywności wszechczasów"),
        ("!czas-specjalny", "Specjalny kanał (Pt/Sb 20–02)"),
        ("!czas-kto [@nick]", "Statystyki konkretnej osoby"),
        ("!czas-online", "Kto teraz siedzi na voice"),
        ("!pomoc", "Ta wiadomość"),
    ]
    for name, desc in cmds:
        embed.add_field(name=name, value=desc, inline=False)
    await ctx.send(embed=embed)

# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)
