import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import Database
from tracker import VoiceTracker
from stats import StatsFormatter

# ── Konfiguracja ──────────────────────────────────────────────────────────────
TOKEN              = os.getenv("DISCORD_TOKEN")
PREFIX             = os.getenv("COMMAND_PREFIX", "!")
SPECIAL_CHANNEL_ID = int(os.getenv("SPECIAL_CHANNEL_ID", "0"))
REPORT_CHANNEL_ID  = int(os.getenv("REPORT_CHANNEL_ID", "0"))      # kanał na auto-raporty
ROLE_ANNOUNCE_ID   = int(os.getenv("ROLE_ANNOUNCE_CHANNEL_ID", "0")) # kanał na info o nadaniu roli
STATS_ROLE_ID      = int(os.getenv("STATS_ROLE_ID", "0"))           # ranga uprawniona do komend
TZ_NAME            = os.getenv("TIMEZONE", "Europe/Warsaw")
LOCAL_TZ           = ZoneInfo(TZ_NAME)

# Stałe progi ról (w sekundach)
# OPIERZONY: 48h = 172800s, następna ranga: 96h = 345600s
# Konfiguracja: ROLE_OPIERZONY_ID i ROLE_BROJLER_ID ustawiane jako zmienne środowiskowe
ROLE_PISKLAK_ID    = int(os.getenv("ROLE_PISKLAK_ID", "0"))   # ranga startowa do USUNIĘCIA przy 48h
ROLE_OPIERZONY_ID  = int(os.getenv("ROLE_OPIERZONY_ID", "0")) # nadawana przy 48h, usuwana przy 96h
ROLE_BROJLER_ID    = int(os.getenv("ROLE_BROJLER_ID", "0"))   # nadawana przy 96h

THRESHOLD_48H = 48 * 3600   # 172 800 s
THRESHOLD_96H = 96 * 3600   # 345 600 s

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
    """
    Przepuszcza tylko administratorów serwera oraz osoby z rangą STATS_ROLE_ID.
    Jeśli STATS_ROLE_ID nie jest ustawione – blokuje wszystkich poza adminami.
    Nieuprawnionym bot nie odpowiada w ogóle (cisza).
    """
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if STATS_ROLE_ID == 0:
            return False  # brak konfiguracji = blokada dla wszystkich poza adminami
        return any(r.id == STATS_ROLE_ID for r in ctx.author.roles)
    return commands.check(predicate)

# ── Eventy ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅  Zalogowano jako {bot.user} ({bot.user.id})")
    print(f"📊  Baza: {db.db_url[:40]}...")
    await db.init()
    save_sessions.start()
    monthly_report_task.start()
    quarterly_report_task.start()
    role_updater.start()
    print(f"⏱️   Tracker uruchomiony. Strefa: {TZ_NAME}")

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
    """1. dzień miesiąca o 10:00 – raport miesięczny."""
    now = datetime.now(LOCAL_TZ)
    if now.day == 1 and now.hour == 10 and now.minute == 0:
        await _send_monthly_report()

@tasks.loop(minutes=1)
async def quarterly_report_task():
    """1. dzień kwartału (styczeń/kwiecień/lipiec/październik) o 10:00 – raport kwartalny."""
    now = datetime.now(LOCAL_TZ)
    if now.month in (1, 4, 7, 10) and now.day == 1 and now.hour == 10 and now.minute == 0:
        await _send_quarterly_report()

@tasks.loop(hours=1)
async def role_updater():
    """Co godzinę sprawdza progi aktywności i aktualizuje role."""
    for guild in bot.guilds:
        await _update_activity_roles(guild, announce=True)

# ── Logika raportów ───────────────────────────────────────────────────────────

async def _get_report_channel():
    if REPORT_CHANNEL_ID == 0:
        print("⚠️  REPORT_CHANNEL_ID nie ustawiony.")
        return None
    ch = bot.get_channel(REPORT_CHANNEL_ID)
    if not ch:
        print(f"⚠️  Nie znalazłem kanału {REPORT_CHANNEL_ID}.")
    return ch

async def _send_monthly_report():
    ch = await _get_report_channel()
    if not ch:
        return
    now   = datetime.now(LOCAL_TZ)
    # Poprzedni miesiąc
    month = now.month - 1 if now.month > 1 else 12
    year  = now.year if now.month > 1 else now.year - 1
    MONTH_PL = ["","Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
                "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"]

    rows  = await db.get_stats(period="month")
    embed = fmt.build_embed(
        rows,
        f"📆 Raport miesięczny – {MONTH_PL[month]} {year}",
        discord.Color.green()
    )
    embed.set_footer(text="Automatyczny raport – 1. dzień każdego miesiąca o 10:00")
    await ch.send(embed=embed)
    print(f"📨  Wysłano raport miesięczny.")

async def _send_quarterly_report():
    ch = await _get_report_channel()
    if not ch:
        return
    now     = datetime.now(LOCAL_TZ)
    quarter = (now.month - 1) // 3  # aktualny kwartał to właśnie skończony
    q_label = f"Q{quarter} {now.year}" if quarter > 0 else f"Q4 {now.year - 1}"

    rows  = await db.get_stats(period="quarter")
    embed = fmt.build_embed(
        rows,
        f"📊 Raport kwartalny – {q_label}",
        discord.Color.orange()
    )

    # Dołącz listę nieaktywnych memberów
    inactive = await _get_inactive_members()
    if inactive:
        lines = []
        for m in inactive:
            joined = m.joined_at.strftime("%d.%m.%Y") if m.joined_at else "?"
            lines.append(f"👤 **{m.display_name}** – na serwerze od {joined}")
        # Discord limit pola: 1024 znaków; dziel jeśli długa lista
        chunk, chunks = [], []
        for line in lines:
            if sum(len(l)+1 for l in chunk) + len(line) > 1000:
                chunks.append("\n".join(chunk))
                chunk = []
            chunk.append(line)
        if chunk:
            chunks.append("\n".join(chunk))
        for i, text in enumerate(chunks):
            name = "😴 Nigdy nie byli na kanałach głosowych" if i == 0 else "↪️ ciąg dalszy"
            embed.add_field(name=name, value=text, inline=False)
    else:
        embed.add_field(name="😴 Nieaktywni", value="Wszyscy członkowie byli aktywni – brawo!", inline=False)

    embed.set_footer(text="Automatyczny raport kwartalny – 1 stycznia / kwietnia / lipca / października o 10:00")
    await ch.send(embed=embed)
    print(f"📨  Wysłano raport kwartalny.")

async def _get_inactive_members() -> list[discord.Member]:
    """Zwraca listę memberów którzy nigdy nie pojawili się na żadnym kanale głosowym."""
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
    """
    Sprawdza każdego membera i nadaje/odbiera role wg progów:
      < 48h  → brak zmian (może mieć PISKLAK jeśli ręcznie nadano)
      ≥ 48h  → OPIERZONY, usuń PISKLAK
      ≥ 96h  → ROLE_96H,  usuń OPIERZONY (i PISKLAK)
    """
    if not any([ROLE_PISKLAK_ID, ROLE_OPIERZONY_ID, ROLE_BROJLER_ID]):
        return

    rows         = await db.get_stats(period="alltime")
    user_seconds = {r["user_id"]: int(r["total_seconds"] or 0) for r in rows}
    announce_ch  = bot.get_channel(ROLE_ANNOUNCE_ID) if announce and ROLE_ANNOUNCE_ID else None

    for member in guild.members:
        if member.bot:
            continue
        total = user_seconds.get(member.id, 0)
        await _apply_roles(member, total, announce_ch)

async def _apply_roles(member: discord.Member, total_seconds: int, announce_ch):
    """Aplikuje właściwe role dla jednego membera."""
    guild = member.guild

    role_pisklak   = guild.get_role(ROLE_PISKLAK_ID)   if ROLE_PISKLAK_ID   else None
    role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
    role_96h       = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None

    try:
        # ── Próg 96h ────────────────────────────────────────────────────────
        if total_seconds >= THRESHOLD_96H and role_96h:
            if role_96h not in member.roles:
                await member.add_roles(role_96h, reason="Voice tracker – 96h aktywności")
                if announce_ch:
                    await announce_ch.send(
                        f"🏆 **{member.mention}** osiągnął(a) **{role_96h.name}**!\n"
                        f"Łącznie spędzono na kanałach głosowych ponad **96 godzin** – "
                        f"to jest prawdziwe poświęcenie! Gratulacje, legendo! 🎉"
                    )
            # Usuń niższe role progowe
            for r in [role_opierzony, role_pisklak]:
                if r and r in member.roles:
                    await member.remove_roles(r, reason="Voice tracker – awans na 96h")

        # ── Próg 48h ────────────────────────────────────────────────────────
        elif total_seconds >= THRESHOLD_48H and role_opierzony:
            if role_opierzony not in member.roles:
                await member.add_roles(role_opierzony, reason="Voice tracker – 48h aktywności")
                if announce_ch:
                    await announce_ch.send(
                        f"🐦 **{member.mention}** właśnie awansował(a) na **{role_opierzony.name}**!\n"
                        f"Skrzydła już nie takie miękkie – ponad **48 godzin** na kanałach głosowych! "
                        f"Tak trzymać, niepohamowany gadaczku! 🎊"
                    )
            if role_pisklak and role_pisklak in member.roles:
                await member.remove_roles(role_pisklak, reason="Voice tracker – awans na OPIERZONY")

    except discord.Forbidden:
        pass  # Bot musi mieć wyższą rolę niż nadawane

# ── Komendy statystyk ─────────────────────────────────────────────────────────

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
        await ctx.send("❌ Specjalny kanał nie jest skonfigurowany (`SPECIAL_CHANNEL_ID`).")
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
    """Jednorazowy test wszystkich automatycznych procesów (tylko admin)."""
    await ctx.send("🧪 Uruchamiam test wszystkich procesów...")

    # Test raportu miesięcznego
    await ctx.send("📆 Wysyłam testowy raport miesięczny...")
    await _send_monthly_report()

    # Test raportu kwartalnego
    await ctx.send("📊 Wysyłam testowy raport kwartalny...")
    await _send_quarterly_report()

    # Test rang – konkretny user
    TEST_USER_ID = 1505984621408551053
    await ctx.send(f"🎖️ Sprawdzam i aktualizuję rangi dla <@{TEST_USER_ID}>...")
    for guild in bot.guilds:
        member = guild.get_member(TEST_USER_ID)
        if member:
            rows         = await db.get_stats(period="alltime")
            user_seconds = {r["user_id"]: int(r["total_seconds"] or 0) for r in rows}
            total        = user_seconds.get(TEST_USER_ID, 0)
            h            = total // 3600
            announce_ch  = bot.get_channel(ROLE_ANNOUNCE_ID) if ROLE_ANNOUNCE_ID else None
            await ctx.send(f"ℹ️ Użytkownik **{member.display_name}** ma łącznie `{h}h` na kanałach głosowych.")
            await _apply_roles(member, total, announce_ch)
            await ctx.send(f"✅ Role dla **{member.display_name}** zaktualizowane.")
        else:
            await ctx.send(f"⚠️ Nie znalazłem użytkownika `{TEST_USER_ID}` na żadnym serwerze.")

    await ctx.send("✅ Test zakończony.")


@has_stats_role()
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 Komendy bota", color=discord.Color.blurple())
    cmds = [
        ("!czas-tydzień",      "Ranking aktywności – ostatnie 7 dni"),
        ("!czas-miesiąc",      "Ranking aktywności – ostatnie 30 dni"),
        ("!czas-kwartał",      "Ranking aktywności – ostatnie 3 miesiące"),
        ("!czas-alltime",      "Ranking aktywności – wszystkie czasy"),
        ("!czas-afazja",       "Kanał Afazja – Pt/Sb 20:00–06:00"),
        ("!czas-kto [@nick]",  "Statystyki konkretnej osoby"),
        ("!pomoc",             "Ta wiadomość"),
    ]
    for name, desc in cmds:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text="Raport miesięczny: 1. dzień miesiąca 10:00 | Kwartalny: 1 sty/kwi/lip/paź 10:00")
    await ctx.send(embed=embed)

# ── Obsługa błędu braku uprawnień ─────────────────────────────────────────────

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        # Cicha blokada – usuń wiadomość, zero odpowiedzi od bota
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # bot nie ma uprawnień do usuwania wiadomości – po prostu ignoruj
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Nie znalazłem takiego użytkownika.")
    else:
        print(f"Błąd komendy: {error}")

# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)
