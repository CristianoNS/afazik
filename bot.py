import discord
from discord.ext import commands, tasks
from aiohttp import web
import asyncio
import os
import json
import secrets
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import Database
from tracker import VoiceTracker
from stats import StatsFormatter

# ── Konfiguracja ───────────────────────────────────────────────────────────────
TOKEN              = os.getenv("DISCORD_TOKEN")
PREFIX             = os.getenv("COMMAND_PREFIX", "!")
SPECIAL_CHANNEL_ID = int(os.getenv("SPECIAL_CHANNEL_ID", "0"))
REPORT_CHANNEL_ID  = int(os.getenv("REPORT_CHANNEL_ID", "0"))
STATS_ROLE_ID      = int(os.getenv("STATS_ROLE_ID", "0"))
TZ_NAME            = os.getenv("TIMEZONE", "Europe/Warsaw")
LOCAL_TZ           = ZoneInfo(TZ_NAME)
ROLE_PISKLAK_ID    = int(os.getenv("ROLE_PISKLAK_ID", "0"))
ROLE_OPIERZONY_ID  = int(os.getenv("ROLE_OPIERZONY_ID", "0"))
ROLE_BROJLER_ID    = int(os.getenv("ROLE_BROJLER_ID", "0"))
DASHBOARD_SECRET   = os.getenv("DASHBOARD_SECRET", secrets.token_hex(32))
DASHBOARD_PORT     = int(os.getenv("PORT", "8080"))
AFK_CHANNEL_ID     = 1487890304362217562

# ── Ogłoszenia Afazja ──────────────────────────────────────────────────────────
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
ANNOUNCE_IMAGE_URL  = os.getenv("ANNOUNCE_IMAGE_URL", "")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
intents.members         = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command("help")

BOT_START_TIME = time.monotonic()  # do liczenia uptime

db      = Database()
tracker = VoiceTracker(db, SPECIAL_CHANNEL_ID)
fmt     = StatsFormatter()

# ── Uprawnienia ───────────────────────────────────────────────────────────────

def has_stats_role():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if STATS_ROLE_ID == 0:
            return False
        return any(r.id == STATS_ROLE_ID for r in ctx.author.roles)
    return commands.check(predicate)

# ── Eventy ─────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅  Zalogowano jako {bot.user} ({bot.user.id})")
    await db.init()
    save_sessions.start()
    monthly_report_task.start()
    quarterly_report_task.start()
    afazja_announcer.start()
    print(f"🌐  Dashboard HTTP na porcie {DASHBOARD_PORT}")

def _is_deaf(vs) -> bool:
    return vs.deaf or vs.self_deaf

@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.utcnow()
    channel_changed = before.channel != after.channel
    deaf_changed    = (before.deaf != after.deaf) or (before.self_deaf != after.self_deaf)

    if channel_changed:
        if after.channel and after.channel.id != AFK_CHANNEL_ID:
            if not _is_deaf(after):
                tracker.join(member.id, member.display_name, after.channel.id, after.channel.name, now)
        if before.channel and before.channel.id != AFK_CHANNEL_ID:
            await tracker.leave(member.id, before.channel.id, now)
    elif deaf_changed and after.channel and after.channel.id != AFK_CHANNEL_ID:
        if _is_deaf(after):
            await tracker.leave(member.id, after.channel.id, now)
        else:
            tracker.join(member.id, member.display_name, after.channel.id, after.channel.name, now)

# ── Zadania cykliczne ─────────────────────────────────────────────────────────

@tasks.loop(minutes=5)
async def save_sessions():
    await tracker.flush_active(datetime.utcnow())

@tasks.loop(minutes=1)
async def monthly_report_task():
    now = datetime.now(LOCAL_TZ)
    if now.day == 1 and now.hour == 10 and now.minute == 0:
        await _send_monthly_report()

@tasks.loop(minutes=1)
async def quarterly_report_task():
    now = datetime.now(LOCAL_TZ)
    if now.month in (1, 4, 7, 10) and now.day == 1 and now.hour == 10 and now.minute == 0:
        await _send_quarterly_report()

# ── Ogłoszenia Afazja ──────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def afazja_announcer():
    now = datetime.now(LOCAL_TZ)
    wd  = now.weekday()
    if wd not in (4, 5):
        return
    if ANNOUNCE_CHANNEL_ID == 0:
        return
    if now.hour == 10 and now.minute == 0:
        await _send_afazja_main(wd)
    elif now.hour == 15 and now.minute == 0:
        await _send_afazja_reminder_1()
    elif now.hour == 19 and now.minute == 0:
        await _send_afazja_reminder_2()

def _mentions() -> str:
    parts = []
    for role_id in [ROLE_BROJLER_ID, ROLE_OPIERZONY_ID, ROLE_PISKLAK_ID]:
        if role_id:
            parts.append(f"<@&{role_id}>")
    return " ".join(parts)

async def _send_afazja_main(weekday: int = 5):
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        return
    mentions = _mentions()
    title = "Nieloty, pora na piątkową afazję!" if weekday == 4 else "Nieloty, pora na sobotnią afazję!"
    opis = (
        "Dosyć siedzenia w kurniku i dziobania ziarna! Wpadnij na event sprawdzić, komu pierwszemu **odpadną pióra**. "
        "Gwarantujemy taki kocioł, że zapomnisz jak się nazywasz. Jak zawsze: gramy 4fun!\n\n"
        "🕗 **Widzimy się tutaj:** <#1485261013434765376>\n\n"
        "Znieś jajo pod postem *(rzuć reakcję)*, jeśli meldujesz się na grzędzie!"
    )
    embed = discord.Embed(title=title, description=opis)
    if ANNOUNCE_IMAGE_URL:
        embed.set_image(url=ANNOUNCE_IMAGE_URL)
    msg = await ch.send(content=mentions, embed=embed)
    await msg.add_reaction("🥚")

async def _send_afazja_reminder_1():
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        return
    mentions = _mentions()
    opis = (
        "Hej nieloty! Wieczorna afazja zbliża się wielkimi krokami. "
        "Rozgrzejcie gardła, nastrojcie klawiatury i przypomnijcie znajomym. "
        "Do zobaczenia na kanale!\n\n"
        "🕛 **Widzimy się tutaj:** <#1485261013434765376>"
    )
    embed = discord.Embed(title="Jeszcze tylko kilka godzin!", description=opis)
    if ANNOUNCE_IMAGE_URL:
        embed.set_image(url=ANNOUNCE_IMAGE_URL)
    await ch.send(content=mentions, embed=embed)

async def _send_afazja_reminder_2():
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        return
    mentions = _mentions()
    opis = (
        "Dość gdakania na czacie — czas wejść na kanał i pokazać co potrafisz. "
        "Do zobaczenia na grzędzi!\n\n"
        "🕛 **Widzimy się tutaj:** <#1485261013434765376>"
    )
    embed = discord.Embed(title="Zaczynamy za chwilę!", description=opis)
    if ANNOUNCE_IMAGE_URL:
        embed.set_image(url=ANNOUNCE_IMAGE_URL)
    await ch.send(content=mentions, embed=embed)

# ── Logika raportów ────────────────────────────────────────────────────────────

async def _get_report_channel():
    if REPORT_CHANNEL_ID == 0:
        return None
    return bot.get_channel(REPORT_CHANNEL_ID)

async def _send_monthly_report():
    ch = await _get_report_channel()
    if not ch:
        return
    now   = datetime.now(LOCAL_TZ)
    month = now.month - 1 if now.month > 1 else 12
    year  = now.year if now.month > 1 else now.year - 1
    MONTH_PL = ["","Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
                "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"]
    rows  = await db.get_stats(period="month")
    embed = fmt.build_embed(rows, f"📆 Raport miesięczny – {MONTH_PL[month]} {year}", discord.Color.green())
    embed.set_footer(text="Automatyczny raport – 1. dzień każdego miesiąca o 10:00")
    await ch.send(embed=embed)
    await db.log_report("monthly", len(rows))

async def _send_quarterly_report():
    ch = await _get_report_channel()
    if not ch:
        return
    now     = datetime.now(LOCAL_TZ)
    quarter = (now.month - 1) // 3
    q_label = f"Q{quarter} {now.year}" if quarter > 0 else f"Q4 {now.year - 1}"
    rows    = await db.get_stats(period="quarter")
    embed   = fmt.build_embed(rows, f"📊 Raport kwartalny – {q_label}", discord.Color.orange())
    inactive = await _get_inactive_members()
    if inactive:
        lines, chunk, chunks = [], [], []
        for m in inactive:
            joined = m.joined_at.strftime("%d.%m.%Y") if m.joined_at else "?"
            lines.append(f"👤 **{m.display_name}** – na serwerze od {joined}")
        for line in lines:
            if sum(len(l)+1 for l in chunk) + len(line) > 1000:
                chunks.append("\n".join(chunk)); chunk = []
            chunk.append(line)
        if chunk:
            chunks.append("\n".join(chunk))
        for i, text in enumerate(chunks):
            embed.add_field(name="😴 Nigdy nie byli na kanałach głosowych" if i == 0 else "↪️ ciąg dalszy",
                            value=text, inline=False)
    else:
        embed.add_field(name="😴 Nieaktywni", value="Wszyscy członkowie byli aktywni – brawo!", inline=False)
    embed.set_footer(text="Automatyczny raport kwartalny")
    await ch.send(embed=embed)
    await db.log_report("quarterly", len(rows))

async def _get_inactive_members() -> list[discord.Member]:
    active_ids = await db.get_all_voice_user_ids()
    result = []
    for guild in bot.guilds:
        for member in guild.members:
            if member.bot:
                continue
            if member.id not in active_ids:
                result.append(member)
    return sorted(result, key=lambda m: m.joined_at or datetime.min.replace(tzinfo=timezone.utc))

# ── Komendy ────────────────────────────────────────────────────────────────────

@bot.command(name="czas-tydzien", aliases=["czas-tydzień"])
@has_stats_role()
async def stats_week(ctx):
    rows  = await db.get_stats(period="week")
    embed = fmt.build_embed(rows, "📅 Aktywność – ostatnie 7 dni", discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="czas-miesiac", aliases=["czas-miesiąc"])
@has_stats_role()
async def stats_month(ctx):
    rows  = await db.get_stats(period="month")
    embed = fmt.build_embed(rows, "📆 Aktywność – ostatnie 30 dni", discord.Color.green())
    await ctx.send(embed=embed)

@bot.command(name="czas-kwartal", aliases=["czas-kwartał"])
@has_stats_role()
async def stats_quarter(ctx):
    rows  = await db.get_stats(period="quarter")
    embed = fmt.build_embed(rows, "📊 Aktywność – ostatnie 3 miesiące", discord.Color.orange())
    await ctx.send(embed=embed)

@bot.command(name="czas-alltime")
@has_stats_role()
async def stats_alltime(ctx):
    rows  = await db.get_stats(period="alltime")
    embed = fmt.build_embed(rows, "🏆 Aktywność – wszystkie czasy", discord.Color.gold())
    await ctx.send(embed=embed)

@bot.command(name="czas-afazja")
@has_stats_role()
async def stats_special(ctx):
    if SPECIAL_CHANNEL_ID == 0:
        await ctx.send("❌ Specjalny kanał nie jest skonfigurowany.")
        return
    rows  = await db.get_special_stats()
    embed = fmt.build_embed(rows, "🎉 Afazja – Pt/Sb 20:00–06:00 (all time)", discord.Color.purple())
    await ctx.send(embed=embed)

@bot.command(name="czas-kto")
@has_stats_role()
async def stats_user(ctx, *, member: discord.Member = None):
    target = member or ctx.author
    rows   = await db.get_user_stats(target.id)
    embed  = fmt.build_user_embed(rows, target.display_name)
    await ctx.send(embed=embed)

@bot.command(name="pomoc", aliases=["help"])
@has_stats_role()
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Komendy bota", color=discord.Color.blurple())
    cmds  = [
        ("!czas-tydzień",     "Ranking aktywności – ostatnie 7 dni"),
        ("!czas-miesiąc",     "Ranking aktywności – ostatnie 30 dni"),
        ("!czas-kwartał",     "Ranking aktywności – ostatnie 3 miesiące"),
        ("!czas-alltime",     "Ranking aktywności – wszystkie czasy"),
        ("!czas-afazja",      "Kanał Afazja – Pt/Sb 20:00–06:00"),
        ("!czas-kto [@nick]", "Statystyki konkretnej osoby"),
        ("!pomoc",            "Ta wiadomość"),
    ]
    for name, desc in cmds:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text="Raport miesięczny: 1. dzień miesiąca 10:00 | Kwartalny: 1 sty/kwi/lip/paź 10:00")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Nie znalazłem takiego użytkownika.")
    else:
        print(f"Błąd komendy: {error}")

# ── HTTP API dla dashboardu ────────────────────────────────────────────────────

def _auth(request: web.Request) -> bool:
    return request.headers.get("Authorization", "") == f"Bearer {DASHBOARD_SECRET}"

def _json(data) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json"
    )

async def api_stats(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_stats(period=request.match_info.get("period", "week")))

async def api_special(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_special_stats())

async def api_reports(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_report_log())

async def api_inactive(request):
    if not _auth(request): return web.Response(status=401)
    members = await _get_inactive_members()
    return _json([{"display_name": m.display_name,
                   "joined_at": m.joined_at.isoformat() if m.joined_at else None}
                  for m in members])

async def api_role_grants(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_role_grants())

async def api_activity_chart(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_daily_activity(days=30))

async def api_online(request):
    if not _auth(request): return web.Response(status=401)
    now = datetime.utcnow()
    return _json([{
        "user_id":      uid,
        "display_name": s["display_name"],
        "channel_name": s["channel_name"],
        "elapsed_s":    int((now - s["joined"]).total_seconds()),
        "is_special":   s.get("is_special", False),
    } for uid, s in tracker.active.items()])

async def api_member_roles(request):
    """Zwraca rangę każdego membera — świeże dane z Discord API (nie cache)."""
    if not _auth(request): return web.Response(status=401)
    result = {}
    for guild in bot.guilds:
        role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
        role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
        try:
            # fetch_members pobiera świeże dane z API, omijając stary cache
            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue
                member_role_ids = {r.id for r in member.roles}
                if role_brojler and role_brojler.id in member_role_ids:
                    rank = "BROJLER"
                elif role_opierzony and role_opierzony.id in member_role_ids:
                    rank = "OPIERZONY"
                else:
                    rank = "PISKLAK"
                result[str(member.id)] = {
                    "display_name": member.display_name,
                    "rank": rank,
                }
        except Exception as e:
            print(f"fetch_members error: {e}")
            # Fallback do cache jeśli API nie odpowiada
            for member in guild.members:
                if member.bot:
                    continue
                member_role_ids = {r.id for r in member.roles}
                if role_brojler and role_brojler.id in member_role_ids:
                    rank = "BROJLER"
                elif role_opierzony and role_opierzony.id in member_role_ids:
                    rank = "OPIERZONY"
                else:
                    rank = "PISKLAK"
                result[str(member.id)] = {
                    "display_name": member.display_name,
                    "rank": rank,
                }
    return _json(result)

async def api_monthly_activity(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_monthly_activity())

async def api_weekly_activity(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_weekly_activity())

async def api_records(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_records())

async def api_server_stats(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_server_stats())

def _fmt_uptime(seconds: int) -> str:
    """Zamienia sekundy na czytelny format Xd Yh Zmin."""
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, _   = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    parts.append(f"{m}min")
    return " ".join(parts)

async def api_health(request):
    """Rozszerzony health-check – status bota, bazy i śledzenia głosowego."""
    uptime_s = time.monotonic() - BOT_START_TIME

    # Sprawdź żywotność połączenia z bazą prostym zapytaniem
    db_connected = False
    db_latency_ms = None
    try:
        t0 = time.monotonic()
        async with db.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_latency_ms = round((time.monotonic() - t0) * 1000, 1)
        db_connected = True
    except Exception as e:
        print(f"health-check: błąd bazy – {e}")

    return _json({
        "status":                "ok" if db_connected else "degraded",
        "bot":                   str(bot.user) if bot.user else None,
        "uptime_seconds":        round(uptime_s, 1),
        "uptime_human":          _fmt_uptime(uptime_s),
        "guilds_connected":      len(bot.guilds),
        "active_voice_sessions": len(tracker.active),
        "database_connected":    db_connected,
        "database_latency_ms":  db_latency_ms,
        "discord_latency_ms":    round(bot.latency * 1000, 1) if bot.latency else None,
    })

def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health",           api_health)
    app.router.add_get("/api/online",           api_online)
    app.router.add_get("/api/stats/{period}",   api_stats)
    app.router.add_get("/api/special",          api_special)
    app.router.add_get("/api/reports",          api_reports)
    app.router.add_get("/api/inactive",         api_inactive)
    app.router.add_get("/api/role-grants",      api_role_grants)
    app.router.add_get("/api/activity-chart",   api_activity_chart)
    app.router.add_get("/api/member-roles",     api_member_roles)
    app.router.add_get("/api/monthly-activity", api_monthly_activity)
    app.router.add_get("/api/weekly-activity",  api_weekly_activity)
    app.router.add_get("/api/records",          api_records)
    app.router.add_get("/api/server-stats",     api_server_stats)
    return app

async def main():
    app    = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site   = web.TCPSite(runner, "0.0.0.0", DASHBOARD_PORT)
    await site.start()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
