import discord
from discord.ext import commands, tasks
from aiohttp import web
import asyncio
import os
import json
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import Database
from tracker import VoiceTracker
from stats import StatsFormatter

# ── Konfiguracja środowiskowa (stała, nie edytowalna z dashboardu) ─────────────
TOKEN              = os.getenv("DISCORD_TOKEN")
PREFIX             = os.getenv("COMMAND_PREFIX", "!")
SPECIAL_CHANNEL_ID = int(os.getenv("SPECIAL_CHANNEL_ID", "0"))
REPORT_CHANNEL_ID  = int(os.getenv("REPORT_CHANNEL_ID", "0"))
ROLE_ANNOUNCE_ID   = int(os.getenv("ROLE_ANNOUNCE_CHANNEL_ID", "0"))
STATS_ROLE_ID      = int(os.getenv("STATS_ROLE_ID", "0"))
TZ_NAME            = os.getenv("TIMEZONE", "Europe/Warsaw")
LOCAL_TZ           = ZoneInfo(TZ_NAME)

ROLE_PISKLAK_ID   = int(os.getenv("ROLE_PISKLAK_ID", "0"))
ROLE_OPIERZONY_ID = int(os.getenv("ROLE_OPIERZONY_ID", "0"))
ROLE_BROJLER_ID   = int(os.getenv("ROLE_BROJLER_ID", "0"))

RULES_MESSAGE_ID  = int(os.getenv("RULES_MESSAGE_ID", "0"))
RULES_CHANNEL_ID  = int(os.getenv("RULES_CHANNEL_ID", "0"))
VERIFIED_ROLE_ID  = int(os.getenv("VERIFIED_ROLE_ID", "0"))

DASHBOARD_SECRET  = os.getenv("DASHBOARD_SECRET", secrets.token_hex(32))
DASHBOARD_PORT    = int(os.getenv("PORT", "8080"))

# ── Ustawienia stałe ─────────────────────────────────────────────────────────
RULES_REACTION      = os.getenv("RULES_REACTION", "👍")
KICK_AFTER_HOURS    = 48
THRESHOLD_OPIERZONY = 48   # godziny
THRESHOLD_BROJLER   = 96   # godziny
MSG_VERIFIED        = "✅ Witaj na serwerze! Zaakceptowałeś/aś regulamin i masz teraz pełny dostęp. Miłej zabawy! 🎉"
MSG_KICK            = "👋 Zostałeś/aś usunięty/a z serwera, ponieważ nie zaakceptowałeś/aś regulaminu w ciągu {hours} godzin. Możesz dołączyć ponownie i zaakceptować regulamin."
MSG_OPIERZONY       = "🐦 **{mention}** właśnie awansował(a) na **{role}**!\nSkrzydła już nie takie miękkie – ponad **{hours}h** na kanałach! Tak trzymać, niepohamowany gadaczku! 🎊"
MSG_BROJLER         = "🏆 **{mention}** osiągnął(a) **{role}**!\nŁącznie ponad **{hours}h** na kanałach głosowych – to jest prawdziwe poświęcenie! Gratulacje, legendo! 🎉"

pending_verification: dict[int, datetime] = {}

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
intents.members         = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command("help")

db      = Database()
tracker = VoiceTracker(db, SPECIAL_CHANNEL_ID)
fmt     = StatsFormatter()

# ── Dekorator uprawnień ───────────────────────────────────────────────────────

def has_stats_role():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if STATS_ROLE_ID == 0:
            return False
        return any(r.id == STATS_ROLE_ID for r in ctx.author.roles)
    return commands.check(predicate)

# ── Eventy ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅  Zalogowano jako {bot.user} ({bot.user.id})")
    await db.init()
    save_sessions.start()
    monthly_report_task.start()
    quarterly_report_task.start()
    role_updater.start()
    verification_checker.start()

    if VERIFIED_ROLE_ID != 0:
        for guild in bot.guilds:
            verified_role = guild.get_role(VERIFIED_ROLE_ID)
            for member in guild.members:
                if member.bot:
                    continue
                if verified_role and verified_role in member.roles:
                    continue
                if member.joined_at:
                    pending_verification[member.id] = member.joined_at.replace(tzinfo=None)
        print(f"📋  Załadowano {len(pending_verification)} osób oczekujących na weryfikację.")
    print(f"🌐  Dashboard HTTP na porcie {DASHBOARD_PORT}")

@bot.event
async def on_member_join(member: discord.Member):
    if member.bot or VERIFIED_ROLE_ID == 0:
        return
    pending_verification[member.id] = datetime.utcnow()

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if RULES_MESSAGE_ID == 0 or VERIFIED_ROLE_ID == 0:
        return
    if payload.message_id != RULES_MESSAGE_ID:
        return
    if payload.user_id == bot.user.id:
        return

    guild  = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return

    verified_role = guild.get_role(VERIFIED_ROLE_ID)
    if not verified_role or verified_role in member.roles:
        return

    try:
        await member.add_roles(verified_role, reason="Akceptacja regulaminu")
        pending_verification.pop(member.id, None)
        try:
            await member.send(MSG_VERIFIED)
        except discord.Forbidden:
            pass
    except discord.Forbidden:
        pass

@bot.event
async def on_voice_state_update(member, before, after):
    now = datetime.utcnow()
    if after.channel and (not before.channel or before.channel.id != after.channel.id):
        tracker.join(member.id, member.display_name, after.channel.id, after.channel.name, now)
    if before.channel and (not after.channel or before.channel.id != after.channel.id):
        await tracker.leave(member.id, before.channel.id, now)

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

@tasks.loop(hours=1)
async def verification_checker():
    if VERIFIED_ROLE_ID == 0:
        return
    now     = datetime.utcnow()
    to_kick = [uid for uid, jt in list(pending_verification.items())
               if (now - jt.replace(tzinfo=None)).total_seconds() / 3600 >= KICK_AFTER_HOURS]
    for guild in bot.guilds:
        for user_id in to_kick:
            member = guild.get_member(user_id)
            if not member:
                pending_verification.pop(user_id, None)
                continue
            try:
                await member.send(MSG_KICK.format(hours=KICK_AFTER_HOURS))
            except discord.Forbidden:
                pass
            try:
                await member.kick(reason=f"Brak akceptacji regulaminu w ciągu {KICK_AFTER_HOURS}h")
                pending_verification.pop(user_id, None)
            except discord.Forbidden:
                pass

@tasks.loop(hours=1)
async def role_updater():
    for guild in bot.guilds:
        await _update_activity_roles(guild, announce=True)

# ── Logika raportów ───────────────────────────────────────────────────────────

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

# ── Logika ról aktywności ─────────────────────────────────────────────────────

async def _update_activity_roles(guild: discord.Guild, announce: bool = False):
    if not any([ROLE_PISKLAK_ID, ROLE_OPIERZONY_ID, ROLE_BROJLER_ID]):
        return
    rows         = await db.get_stats(period="alltime")
    user_seconds = {r["user_id"]: int(r["total_seconds"] or 0) for r in rows}
    announce_ch  = bot.get_channel(ROLE_ANNOUNCE_ID) if announce and ROLE_ANNOUNCE_ID else None
    for member in guild.members:
        if member.bot:
            continue
        await _apply_roles(member, user_seconds.get(member.id, 0), announce_ch)

async def _apply_roles(member: discord.Member, total_seconds: int, announce_ch):
    guild          = member.guild
    role_pisklak   = guild.get_role(ROLE_PISKLAK_ID)   if ROLE_PISKLAK_ID   else None
    role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
    role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
    try:
        if total_seconds >= THRESHOLD_BROJLER * 3600 and role_brojler:
            if role_brojler not in member.roles:
                await member.add_roles(role_brojler, reason="Voice tracker – próg BROJLER")
                await db.log_role_grant(member.id, member.display_name, "BROJLER", total_seconds)
                if announce_ch:
                    await announce_ch.send(MSG_BROJLER.format(
                        mention=member.mention,
                        role=role_brojler.name,
                        hours=THRESHOLD_BROJLER
                    ))
            for r in [role_opierzony, role_pisklak]:
                if r and r in member.roles:
                    await member.remove_roles(r, reason="Awans na BROJLER")

        elif total_seconds >= THRESHOLD_OPIERZONY * 3600 and role_opierzony:
            if role_opierzony not in member.roles:
                await member.add_roles(role_opierzony, reason="Voice tracker – próg OPIERZONY")
                await db.log_role_grant(member.id, member.display_name, "OPIERZONY", total_seconds)
                if announce_ch:
                    await announce_ch.send(MSG_OPIERZONY.format(
                        mention=member.mention,
                        role=role_opierzony.name,
                        hours=THRESHOLD_OPIERZONY
                    ))
            if role_pisklak and role_pisklak in member.roles:
                await member.remove_roles(role_pisklak, reason="Awans na OPIERZONY")

    except discord.Forbidden:
        pass

# ── Komendy Discord ───────────────────────────────────────────────────────────

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

@bot.command(name="czas-test")
@commands.has_permissions(administrator=True)
async def test_all(ctx):
    await ctx.send("🧪 Uruchamiam test wszystkich procesów...")
    await _send_monthly_report()
    await _send_quarterly_report()
    TEST_USER_ID = 1505984621408551053
    for guild in bot.guilds:
        member = guild.get_member(TEST_USER_ID)
        if member:
            rows         = await db.get_stats(period="alltime")
            user_seconds = {r["user_id"]: int(r["total_seconds"] or 0) for r in rows}
            total        = user_seconds.get(TEST_USER_ID, 0)
            await _apply_roles(member, total, bot.get_channel(ROLE_ANNOUNCE_ID) if ROLE_ANNOUNCE_ID else None)
            await ctx.send(f"✅ Role dla **{member.display_name}** zaktualizowane.")
    await ctx.send("✅ Test zakończony.")

@bot.command(name="pomoc", aliases=["help"])
@has_stats_role()
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Komendy bota", color=discord.Color.blurple())
    cmds = [
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

# ── HTTP API dla dashboardu ───────────────────────────────────────────────────

def _auth(request: web.Request) -> bool:
    return request.headers.get("Authorization", "") == f"Bearer {DASHBOARD_SECRET}"

def _json(data) -> web.Response:
    return web.Response(text=json.dumps(data, ensure_ascii=False, default=str),
                        content_type="application/json")

async def api_stats(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_stats(period=request.match_info.get("period", "week")))

async def api_special(request):
    if not _auth(request): return web.Response(status=401)
    return _json(await db.get_special_stats())

async def api_online(request):
    if not _auth(request): return web.Response(status=401)
    now = datetime.utcnow()
    return _json([{
        "user_id": uid, "display_name": s["display_name"],
        "channel_name": s["channel_name"],
        "elapsed_s": int((now - s["joined"]).total_seconds()),
        "is_special": s.get("is_special", False),
    } for uid, s in tracker.active.items()])

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

async def api_action(request):
    if not _auth(request): return web.Response(status=401)
    try:
        body   = await request.json()
        action = body.get("action", "")
    except Exception:
        return web.Response(status=400)

    if action == "monthly_report":
        asyncio.create_task(_send_monthly_report())
        return _json({"ok": True, "message": "Raport miesięczny wysyłany..."})
    elif action == "quarterly_report":
        asyncio.create_task(_send_quarterly_report())
        return _json({"ok": True, "message": "Raport kwartalny wysyłany..."})
    return _json({"ok": False, "message": f"Nieznana akcja: {action}"})

async def api_health(request):
    return _json({"status": "ok", "bot": str(bot.user)})

def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health",          api_health)
    app.router.add_get("/api/stats/{period}",  api_stats)
    app.router.add_get("/api/special",         api_special)
    app.router.add_get("/api/online",          api_online)
    app.router.add_get("/api/reports",         api_reports)
    app.router.add_get("/api/inactive",        api_inactive)
    app.router.add_get("/api/role-grants",     api_role_grants)
    app.router.add_get("/api/activity-chart",  api_activity_chart)
    app.router.add_post("/api/action",         api_action)
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
