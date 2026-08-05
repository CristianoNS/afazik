import discord
from discord.ext import commands, tasks
from aiohttp import web
import asyncio
import os
import json
import secrets
import signal
import time
import hmac
from datetime import datetime, timezone, timedelta
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
DASHBOARD_SECRET   = os.getenv("DASHBOARD_SECRET", "")
# Bez ustawionego sekretu API jest wyłączone (503) zamiast startować z losowym
# kluczem, który i tak zerwałby łączność z dashboardem przy każdym restarcie.
DASHBOARD_API_ENABLED = bool(DASHBOARD_SECRET)
DASHBOARD_PORT     = int(os.getenv("PORT", "8080"))
# Endpoint /api/debug-roles zrzuca ID, nick i wszystkie role każdego członka.
# Domyślnie wyłączony – włącz tylko na czas diagnozowania (DEBUG_ENDPOINTS=1).
DEBUG_ENDPOINTS    = os.getenv("DEBUG_ENDPOINTS", "0") == "1"
AFK_CHANNEL_ID     = 1487890304362217562
NOTIFICATIONS_CHANNEL_ID = 1529222104384274502  # kanał: przekroczenie progów + nieaktywność z rangą
MAIN_GUILD_ID = 1485261012616610005  # jedyny serwer, na którym bot ma realnie działać
EVENT_VOICE_CHANNEL_ID = 1485261013434765376  # kanał głosowy Afazja (wzmianka w ogłoszeniach)
QUIET_HOURS_START = int(os.getenv("QUIET_HOURS_START", "8"))   # od której godziny wysyłamy powiadomienia
QUIET_HOURS_END   = int(os.getenv("QUIET_HOURS_END", "22"))   # do której godziny (wyłącznie) wysyłamy powiadomienia

# ── Ogłoszenia Afazja ──────────────────────────────────────────────────────────
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
ANNOUNCE_IMAGE_URL  = os.getenv("ANNOUNCE_IMAGE_URL", "")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states    = True
intents.members         = True
intents.invites         = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.remove_command("help")

# Nick użytkownika trafia wprost do treści powiadomień. Nick typu "@everyone"
# albo "<@&ID_ROLI>" pozwoliłby dowolnej osobie z serwera wywołać masowy ping
# rękami bota. NO_PINGS blokuje to całkowicie; ogłoszenia Afazja świadomie
# pingują tylko role z _mentions() i nic poza tym.
NO_PINGS         = discord.AllowedMentions.none()
ROLE_PINGS_ONLY  = discord.AllowedMentions(everyone=False, users=False, roles=True)

def _get_main_guild():
    """Zwraca WYŁĄCZNIE główny serwer (MAIN_GUILD_ID).

    Bot bywa czasem dodany też na inne serwery (np. testowe) – bez tego
    ograniczenia dane osób obecnych na kilku serwerach jednocześnie
    nadpisywały się wzajemnie (np. ranga widoczna na jednym serwerze
    znikała, bo pętla po bot.guilds przetwarzała potem serwer testowy
    bez tej rangi i nadpisywała poprawny wynik).
    """
    return bot.get_guild(MAIN_GUILD_ID)

BOT_START_TIME = time.monotonic()  # do liczenia uptime

db      = Database()
tracker = VoiceTracker(db, SPECIAL_CHANNEL_ID)
fmt     = StatsFormatter()

invite_cache: dict[int, dict[str, int]] = {}  # guild_id -> {kod_zaproszenia: liczba_użyć}

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

# on_ready odpala się przy KAŻDYM reconnecie do Discorda, nie tylko przy starcie.
# Bez tej flagi każdy reconnect tworzyłby nową pulę połączeń do Postgresa
# (wyciek), próbował ponownie wystartować działające już taski (RuntimeError,
# który przerywał resztę on_ready) i duplikował odtworzone sesje głosowe.
_startup_done = False

@bot.event
async def on_ready():
    global _startup_done
    print(f"✅  Zalogowano jako {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.CustomActivity(name="I see you, 24/7."))

    if _startup_done:
        # Reconnect – odśwież tylko to, co mogło się zdezaktualizować w trakcie rozłączenia.
        main_guild = _get_main_guild()
        if main_guild:
            await _refresh_invite_cache(main_guild)
        print("🔄  Reconnect – pominięto ponowną inicjalizację (baza i taski już działają).")
        return

    bot.add_dynamic_items(ReportButton)  # przyciski raportów – przeżywają restart bota
    if not DASHBOARD_API_ENABLED:
        print("⚠️  UWAGA: zmienna DASHBOARD_SECRET nie jest ustawiona w Railway! "
              "HTTP API dashboardu jest WYŁĄCZONE (zwraca 503) – bez tego bot "
              "startowałby z losowym kluczem zmieniającym się przy każdym restarcie. "
              "Ustaw DASHBOARD_SECRET na stałą wartość w Variables.")
    await db.init()

    for task in (save_sessions, monthly_report_task, quarterly_report_task,
                 afazja_announcer, threshold_and_stale_checker, member_snapshot_task):
        if not task.is_running():
            task.start()

    main_guild = _get_main_guild()
    if main_guild:
        await _refresh_invite_cache(main_guild)
        await _recover_active_voice_sessions(main_guild)

    _startup_done = True
    print(f"🌐  Dashboard HTTP na porcie {DASHBOARD_PORT}")

def _is_deaf(vs) -> bool:
    return vs.deaf or vs.self_deaf

async def _recover_active_voice_sessions(guild: discord.Guild):
    """Po restarcie bota – odtwarza w pamięci sesje osób, które są AKTUALNIE
    na kanałach głosowych. Bez tego cała reszta ich sesji (aż do momentu
    faktycznego wyjścia z kanału) byłaby cicho tracona, bo tracker.leave()
    nie znajduje dopasowania w pustym tracker.active po restarcie.

    Uwaga: czas sprzed restartu (od momentu gdy faktycznie weszli na kanał
    do teraz) i tak jest bezpowrotnie stracony – nie da się go odtworzyć,
    bo Discord nie udostępnia historii dołączenia do kanału głosowego.
    Ten mechanizm ratuje tylko czas OD TERAZ do momentu wyjścia.
    """
    now = datetime.utcnow()
    recovered = 0
    for channel in guild.voice_channels:
        if channel.id == AFK_CHANNEL_ID:
            continue
        for member in channel.members:
            if member.bot:
                continue
            if member.voice and _is_deaf(member.voice):
                continue
            tracker.join(member.id, member.display_name, channel.id, channel.name, now)
            recovered += 1
    if recovered:
        print(f"🔄  Odtworzono {recovered} trwających sesji głosowych po restarcie.")

# ── Śledzenie zaproszeń: kto kogo zaprosił ──────────────────────────────────────

async def _refresh_invite_cache(guild: discord.Guild):
    """Zapisuje aktualną liczbę użyć każdego zaproszenia na serwerze."""
    try:
        invites = await guild.invites()
        invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in invites}
    except discord.Forbidden:
        invite_cache[guild.id] = {}
        print(f"⚠️  Brak uprawnienia 'Zarządzaj serwerem' – śledzenie zaproszeń wyłączone dla {guild.name}.")

@bot.event
async def on_invite_create(invite: discord.Invite):
    invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

@bot.event
async def on_invite_delete(invite: discord.Invite):
    invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

@bot.event
async def on_member_join(member: discord.Member):
    """Informuje na kanale kto dołączył i z jakiego zaproszenia skorzystał."""
    if member.bot:
        return
    guild = member.guild
    ch = bot.get_channel(NOTIFICATIONS_CHANNEL_ID)
    if not ch:
        return

    old_cache = invite_cache.get(guild.id, {})
    used_invite = None
    disappeared_code = None

    try:
        new_invites = await guild.invites()
        new_codes = set()
        for inv in new_invites:
            new_codes.add(inv.code)
            if (inv.uses or 0) > old_cache.get(inv.code, 0):
                used_invite = inv
                break

        if used_invite is None:
            # Zaproszenie mogło zniknąć, jeśli było jednorazowe i właśnie się wyczerpało
            for code in old_cache:
                if code not in new_codes:
                    disappeared_code = code
                    break

        invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in new_invites}
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"on_member_join – błąd sprawdzania zaproszeń: {e}")

    if used_invite is not None:
        inviter = used_invite.inviter.display_name if used_invite.inviter else "nieznanego użytkownika"
        await ch.send(
            f"**{member.display_name}** dołączył/a do serwera – zaproszony/a przez {inviter} "
            f"(kod: `{used_invite.code}`).",
            allowed_mentions=NO_PINGS,
        )
    elif disappeared_code is not None:
        await ch.send(
            f"**{member.display_name}** dołączył/a do serwera – prawdopodobnie użył/a "
            f"jednorazowego zaproszenia `{disappeared_code}`, które właśnie wygasło.",
            allowed_mentions=NO_PINGS,
        )
    else:
        # Sprawdź link vanity URL serwera (jeśli serwer go ma)
        try:
            vanity = await guild.vanity_invite()
        except (discord.Forbidden, discord.NotFound):
            vanity = None
        if vanity is not None:
            await ch.send(f"**{member.display_name}** dołączył/a do serwera przez własny link serwera (vanity URL).",
                          allowed_mentions=NO_PINGS)
        else:
            await ch.send(f"**{member.display_name}** dołączył/a do serwera (nie udało się ustalić zaproszenia).",
                          allowed_mentions=NO_PINGS)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return  # boty (np. muzyczne) nigdy nie mają liczonego czasu na kanałach
    now = datetime.utcnow()
    channel_changed = before.channel != after.channel
    deaf_changed    = (before.deaf != after.deaf) or (before.self_deaf != after.self_deaf)

    if channel_changed:
        # UWAGA: LEAVE musi być PRZED JOIN. Odwrotna kolejność powodowała, że
        # tracker.join() nadpisywał wpis w tracker.active, a leave() zdejmował
        # świeżo utworzoną sesję nowego kanału (zamykając ją z czasem ~0s),
        # przez co sesja starego kanału zostawała otwarta na zawsze, a czas na
        # nowym kanale nie był liczony wcale.
        if before.channel and before.channel.id != AFK_CHANNEL_ID:
            await tracker.leave(member.id, before.channel.id, now)
        if after.channel and after.channel.id != AFK_CHANNEL_ID:
            if not _is_deaf(after):
                tracker.join(member.id, member.display_name, after.channel.id, after.channel.name, now)
    elif deaf_changed and after.channel and after.channel.id != AFK_CHANNEL_ID:
        if _is_deaf(after):
            await tracker.leave(member.id, after.channel.id, now)
        else:
            tracker.join(member.id, member.display_name, after.channel.id, after.channel.name, now)

# ── Zadania cykliczne ─────────────────────────────────────────────────────────

@tasks.loop(minutes=5)
async def save_sessions():
    try:
        await tracker.flush_active(datetime.utcnow())
    except Exception as e:
        print(f"⚠️  save_sessions – błąd: {e}")

@tasks.loop(minutes=1)
async def monthly_report_task():
    try:
        now = datetime.now(LOCAL_TZ)
        # Okno 10:00–10:04 (nie tylko dokładna minuta) – jeśli bot akurat
        # restartował się o 10:00, złapiemy to w kolejnych minutach zamiast
        # przegapić cały raport do następnego miesiąca.
        if now.day == 1 and now.hour == 10 and now.minute < 5:
            already_sent = await db.was_report_sent_today("monthly", now.date())
            if not already_sent:
                await _send_monthly_report()
    except Exception as e:
        print(f"⚠️  monthly_report_task – błąd: {e}")

@tasks.loop(minutes=1)
async def quarterly_report_task():
    try:
        now = datetime.now(LOCAL_TZ)
        if now.month in (1, 4, 7, 10) and now.day == 1 and now.hour == 10 and now.minute < 5:
            already_sent = await db.was_report_sent_today("quarterly", now.date())
            if not already_sent:
                await _send_quarterly_report()
    except Exception as e:
        print(f"⚠️  quarterly_report_task – błąd: {e}")

# ── Ogłoszenia Afazja ──────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def afazja_announcer():
    try:
        now = datetime.now(LOCAL_TZ)
        wd  = now.weekday()
        if wd not in (4, 5):
            return
        if ANNOUNCE_CHANNEL_ID == 0:
            return
        # Okno 5-minutowe + dedupe w bazie zamiast dokładnej minuty. Wcześniej
        # restart Railway albo drobny lag pętli o pełnej godzinie oznaczał, że
        # ogłoszenie nie poszło w ogóle – bez żadnego śladu.
        if now.minute >= 5:
            return
        slot = {10: "main", 15: "reminder1", 19: "reminder2"}.get(now.hour)
        if slot is None:
            return
        if await db.was_announce_sent(slot, now.date()):
            return
        if slot == "main":
            await _send_afazja_main(wd)
        elif slot == "reminder1":
            await _send_afazja_reminder_1()
        else:
            await _send_afazja_reminder_2()
        await db.log_announce(slot, now.date())
    except Exception as e:
        print(f"⚠️  afazja_announcer – błąd: {e}")

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
        "🕗 **Widzimy się tutaj:** <#" + str(EVENT_VOICE_CHANNEL_ID) + ">\n\n"
        "Znieś jajo pod postem *(rzuć reakcję)*, jeśli meldujesz się na grzędzie!"
    )
    embed = discord.Embed(title=title, description=opis)
    if ANNOUNCE_IMAGE_URL:
        embed.set_image(url=ANNOUNCE_IMAGE_URL)
    msg = await ch.send(content=mentions, embed=embed, allowed_mentions=ROLE_PINGS_ONLY)
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
        "🕛 **Widzimy się tutaj:** <#" + str(EVENT_VOICE_CHANNEL_ID) + ">"
    )
    embed = discord.Embed(title="Jeszcze tylko kilka godzin!", description=opis)
    if ANNOUNCE_IMAGE_URL:
        embed.set_image(url=ANNOUNCE_IMAGE_URL)
    await ch.send(content=mentions, embed=embed, allowed_mentions=ROLE_PINGS_ONLY)

async def _send_afazja_reminder_2():
    ch = bot.get_channel(ANNOUNCE_CHANNEL_ID)
    if not ch:
        return
    mentions = _mentions()
    opis = (
        "Dość gdakania na czacie — czas wejść na kanał i pokazać co potrafisz. "
        "Do zobaczenia na grzędzi!\n\n"
        "🕛 **Widzimy się tutaj:** <#" + str(EVENT_VOICE_CHANNEL_ID) + ">"
    )
    embed = discord.Embed(title="Zaczynamy za chwilę!", description=opis)
    if ANNOUNCE_IMAGE_URL:
        embed.set_image(url=ANNOUNCE_IMAGE_URL)
    await ch.send(content=mentions, embed=embed, allowed_mentions=ROLE_PINGS_ONLY)

# ── Logika raportów ────────────────────────────────────────────────────────────

async def _get_report_channel():
    if REPORT_CHANNEL_ID == 0:
        return None
    return bot.get_channel(REPORT_CHANNEL_ID)

MONTH_PL = ["","Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
            "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"]
REPORT_PAGE_SIZE   = 10
LONG_INACTIVE_DAYS = 60  # co najmniej 2 miesiące

def _period_label(end_ts: datetime, monthly: bool) -> str:
    """Wyznacza etykietę okresu ("Lipiec 2026" / "Q3 2026") wyłącznie na
    podstawie end_ts – dzięki temu przycisk kliknięty tygodnie później
    odtwarza dokładnie tę samą etykietę bez potrzeby jej zapisywania."""
    local_end = end_ts.astimezone(LOCAL_TZ)
    if monthly:
        return f"{MONTH_PL[local_end.month]} {local_end.year}"
    q = (local_end.month - 1) // 3 + 1
    return f"Q{q} {local_end.year}"

async def _get_ranks_map() -> dict:
    """{user_id_str: 'BROJLER'|'OPIERZONY'|'PISKLAK'} – do odznak w raportach."""
    ranked = await _get_all_members_ranked()
    return {uid: info["rank"] for uid, info in ranked.items()}

async def _build_report_content(start_ts: datetime, end_ts: datetime, mode: str, page: int, monthly: bool):
    """Buduje (embed, view) dla danej strony raportu – wywoływane zarówno
    przy pierwszym wysłaniu jak i przy każdym kliknięciu przycisku."""
    guild = _get_main_guild()
    ranks = await _get_ranks_map() if guild else {}
    label = _period_label(end_ts, monthly)
    color = discord.Color.green() if monthly else discord.Color.orange()

    if mode == "summary":
        summary = await db.get_period_summary(start_ts, end_ts)
        title = f"📆 Raport miesięczny – {label}" if monthly else f"📊 Raport kwartalny – {label}"
        embed = fmt.build_summary_embed(title, summary, color)
        view  = _build_report_view(start_ts, end_ts, monthly, "summary", 0, 1)
        return embed, view

    if mode == "active":
        entries = await db.get_stats_range(start_ts, end_ts)
        embed, total_pages, page = fmt.build_list_embed(
            f"Aktywni – {label}", entries, page, REPORT_PAGE_SIZE, ranks, "active", color)
        view = _build_report_view(start_ts, end_ts, monthly, "active", page, total_pages)
        return embed, view

    # mode == "inactive"
    entries = await _get_long_inactive_members(guild, LONG_INACTIVE_DAYS) if guild else []
    embed, total_pages, page = fmt.build_list_embed(
        f"Nieaktywni {LONG_INACTIVE_DAYS}+ dni – {label}", entries, page, REPORT_PAGE_SIZE, ranks, "inactive",
        discord.Color.red())
    view = _build_report_view(start_ts, end_ts, monthly, "inactive", page, total_pages)
    return embed, view

def _build_report_view(start_ts: datetime, end_ts: datetime, monthly: bool, mode: str, page: int, total_pages: int):
    start_epoch = int(start_ts.timestamp())
    end_epoch   = int(end_ts.timestamp())
    rtype = "m" if monthly else "q"
    view  = discord.ui.View(timeout=None)

    if mode == "summary":
        view.add_item(ReportButton(start_epoch, end_epoch, rtype, "active", 0))
        view.add_item(ReportButton(start_epoch, end_epoch, rtype, "inactive", 0))
    else:
        view.add_item(ReportButton(start_epoch, end_epoch, rtype, "summary", 0))
        if page > 0:
            view.add_item(ReportButton(start_epoch, end_epoch, rtype, mode, page - 1, label="◀"))
        if page < total_pages - 1:
            view.add_item(ReportButton(start_epoch, end_epoch, rtype, mode, page + 1, label="▶"))
    return view

class ReportButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r'rpt\|(?P<start>\d+)\|(?P<end>\d+)\|(?P<rtype>[mq])\|(?P<mode>active|inactive|summary)\|(?P<page>\d+)'):
    """Trwały przycisk raportu – stan (okres/widok/strona) zakodowany w custom_id,
    więc działa nawet po restarcie bota (rejestrowany raz w on_ready)."""

    LABELS = {"active": "Aktywni", "inactive": "Nieaktywni", "summary": "Powrót"}

    def __init__(self, start_epoch: int, end_epoch: int, rtype: str, mode: str, page: int, *, label: str = None):
        super().__init__(discord.ui.Button(
            label=label or self.LABELS.get(mode, mode),
            style=discord.ButtonStyle.secondary,
            custom_id=f"rpt|{start_epoch}|{end_epoch}|{rtype}|{mode}|{page}",
        ))
        self.start_epoch = start_epoch
        self.end_epoch   = end_epoch
        self.rtype = rtype
        self.mode  = mode
        self.page  = page

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["start"]), int(match["end"]), match["rtype"], match["mode"], int(match["page"]))

    async def callback(self, interaction: discord.Interaction):
        start_ts = datetime.fromtimestamp(self.start_epoch, tz=timezone.utc)
        end_ts   = datetime.fromtimestamp(self.end_epoch, tz=timezone.utc)
        monthly  = (self.rtype == "m")
        try:
            embed, view = await _build_report_content(start_ts, end_ts, self.mode, self.page, monthly)
            await interaction.response.edit_message(embed=embed, view=view)
        except Exception as e:
            print(f"⚠️  ReportButton callback – błąd: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Nie udało się załadować danych.", ephemeral=True)

async def _send_monthly_report():
    ch = await _get_report_channel()
    if not ch:
        return
    end_ts   = datetime.now(LOCAL_TZ).astimezone(timezone.utc)
    start_ts = end_ts - timedelta(days=30)
    embed, view = await _build_report_content(start_ts, end_ts, "summary", 0, monthly=True)
    await ch.send(embed=embed, view=view)
    rows = await db.get_stats_range(start_ts, end_ts)
    await db.log_report("monthly", len(rows))

async def _send_quarterly_report():
    ch = await _get_report_channel()
    if not ch:
        return
    end_ts   = datetime.now(LOCAL_TZ).astimezone(timezone.utc)
    start_ts = end_ts - timedelta(days=90)
    embed, view = await _build_report_content(start_ts, end_ts, "summary", 0, monthly=False)
    await ch.send(embed=embed, view=view)
    rows = await db.get_stats_range(start_ts, end_ts)
    await db.log_report("quarterly", len(rows))

async def _get_long_inactive_members(guild: discord.Guild, min_days: int) -> list[dict]:
    """Osoby nieaktywne od co najmniej min_days dni – w tym osoby, które
    nigdy w ogóle nie były aktywne na kanałach głosowych (traktowane jako
    najdłuższy możliwy okres nieaktywności, sortowane na górze listy).
    """
    last_activity = await _get_last_activity_cached()
    now = datetime.now(timezone.utc)
    result = []
    for member in guild.members:
        if member.bot:
            continue
        last_seen = last_activity.get(str(member.id))
        if last_seen is None:
            days_inactive = None  # nigdy nieaktywny
        else:
            days_inactive = (now - last_seen).days
        if days_inactive is None or days_inactive >= min_days:
            result.append({
                "display_name": member.display_name,
                "user_id": str(member.id),
                "days_inactive": days_inactive,
            })
    result.sort(key=lambda r: (r["days_inactive"] is None, r["days_inactive"] or 0), reverse=True)
    return result

async def _get_inactive_members() -> list[discord.Member]:
    active_ids = await db.get_all_voice_user_ids()
    result = []
    guild = _get_main_guild()
    if guild:
        for member in guild.members:
            if member.bot:
                continue
            if member.id not in active_ids:
                result.append(member)
    return sorted(result, key=lambda m: m.joined_at or datetime.min.replace(tzinfo=timezone.utc))

# ── Powiadomienia: progi godzinowe i nieaktywność z rangą ───────────────────────

STALE_DAYS = 30  # ile dni braku aktywności traktujemy jako "nieaktywny z rangą"

# Discord odrzuca embed z description > 4096 znaków. Bez limitu !czas-alltime
# przestawał działać po przekroczeniu ~80 osób w rankingu.
EMBED_RANK_LIMIT = 25

def _is_quiet_hours() -> bool:
    """Sprawdza czy jesteśmy poza oknem aktywnym (domyślnie 8:00–22:00 czasu lokalnego)."""
    hour = datetime.now(LOCAL_TZ).hour
    return not (QUIET_HOURS_START <= hour < QUIET_HOURS_END)

@tasks.loop(hours=1)
async def threshold_and_stale_checker():
    try:
        if _is_quiet_hours():
            return  # poza oknem 8:00–22:00 – nic nie sprawdzamy ani nie wysyłamy;
                    # najbliższe uruchomienie w oknie aktywnym złapie te same zdarzenia
        guild = _get_main_guild()
        if not guild:
            return
        # Odświeżamy wspólny cache ról (ten sam, z którego korzysta dashboard),
        # zamiast robić drugie, niezależne fetch_members(limit=None) co godzinę.
        await _get_all_members_ranked(force_refresh=True)
        members_by_id = {m.id: m for m in guild.members}
        await _check_threshold_crossings(guild, members_by_id)
        await _check_stale_ranks(guild, members_by_id)
    except Exception as e:
        print(f"⚠️  threshold_and_stale_checker – błąd: {e}")

async def _check_threshold_crossings(guild: discord.Guild, members_by_id: dict):
    """Informuje o przekroczeniu progu 48h (OPIERZONY) i 96h (BROJLER).

    Zanim wyśle powiadomienie, sprawdza AKTUALNĄ rangę danej osoby na Discordzie.
    Jeśli osoba już ma daną rangę (np. nadaną wcześniej ręcznie, albo przez
    stary system automatyczny) – zapisuje próg jako "już obsłużony" bez
    wysyłania wiadomości, żeby uniknąć bezsensownych powiadomień typu
    "spełniasz wymóg" dla kogoś kto już tę rangę posiada.
    """
    ch = bot.get_channel(NOTIFICATIONS_CHANNEL_ID)
    if not ch:
        return

    role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
    role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None

    rows = await db.get_stats(period="alltime")
    already_alerted = await db.get_all_threshold_alerts()  # jedno zapytanie zamiast N
    for row in rows:
        user_id = int(row["user_id"])
        secs    = int(row["total_seconds"] or 0)
        name    = row["display_name"] or str(user_id)

        member = members_by_id.get(user_id)
        if member is None or member.bot:
            continue  # osoba już nie na serwerze albo to bot

        member_role_ids = {r.id for r in member.roles}
        has_brojler   = bool(role_brojler   and role_brojler.id   in member_role_ids)
        has_opierzony = bool(role_opierzony and role_opierzony.id in member_role_ids)

        if secs >= 96 * 3600:
            if (user_id, "BROJLER") not in already_alerted:
                if not has_brojler:
                    await ch.send(
                        f"**{name}** przekroczył/a próg **96h** i spełnia wymóg uzyskania rangi **BROJLER**.",
                        allowed_mentions=NO_PINGS,
                    )
                # Zapisujemy jako obsłużone niezależnie od tego czy wysłano wiadomość –
                # jeśli ranga już była, nie chcemy pytać o to ponownie w przyszłości.
                await db.record_threshold_alert(user_id, "BROJLER")

        if secs >= 48 * 3600:
            if (user_id, "OPIERZONY") not in already_alerted:
                if not has_opierzony and not has_brojler:
                    await ch.send(
                        f"**{name}** przekroczył/a próg **48h** i spełnia wymóg uzyskania rangi **OPIERZONY**.",
                        allowed_mentions=NO_PINGS,
                    )
                await db.record_threshold_alert(user_id, "OPIERZONY")

async def _check_stale_ranks(guild: discord.Guild, members_by_id: dict):
    """Informuje gdy osoba z rangą OPIERZONY/BROJLER staje się nieaktywna od STALE_DAYS dni."""
    ch = bot.get_channel(NOTIFICATIONS_CHANNEL_ID)
    if not ch:
        return

    role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
    role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
    last_activity  = await _get_last_activity_cached()
    now = datetime.now(timezone.utc)

    prev_states = await db.get_all_stale_states()  # jeden odczyt zamiast N
    pending: list[tuple[int, bool]] = []           # zbiorczy zapis na końcu

    for member in members_by_id.values():
        if member.bot:
            continue
        member_role_ids = {r.id for r in member.roles}
        if role_brojler and role_brojler.id in member_role_ids:
            rank = "BROJLER"
        elif role_opierzony and role_opierzony.id in member_role_ids:
            rank = "OPIERZONY"
        else:
            # Brak rangi – zresetuj stan, żeby ewentualny przyszły powrót rangi
            # i ponowna nieaktywność znowu wygenerowały powiadomienie.
            # Zapisujemy tylko jeśli faktycznie coś się zmienia.
            if prev_states.get(member.id, False):
                pending.append((member.id, False))
            continue

        last_seen = last_activity.get(str(member.id))
        if last_seen is None:
            days_inactive = None  # nigdy aktywny mimo posiadania rangi
            is_stale = True
        else:
            days_inactive = (now - last_seen).days
            is_stale = days_inactive >= STALE_DAYS

        was_stale = prev_states.get(member.id, False)

        if is_stale and not was_stale:
            days_text = "nigdy nieaktywny/a" if days_inactive is None else f"{days_inactive} dni"
            await ch.send(
                f"**{member.display_name}** jest nieaktywny/a od **{days_text}**. "
                f"Aktualnie ma rangę **{rank}**.",
                allowed_mentions=NO_PINGS,
            )

        if is_stale != was_stale or member.id not in prev_states:
            pending.append((member.id, is_stale))

    await db.set_stale_states_bulk(pending)

# ── Komendy ────────────────────────────────────────────────────────────────────

@bot.command(name="czas-tydzien", aliases=["czas-tydzień"])
@has_stats_role()
async def stats_week(ctx):
    rows  = await db.get_stats(period="week")
    embed = fmt.build_embed(rows, "📅 Aktywność – ostatnie 7 dni", discord.Color.blue(), limit=EMBED_RANK_LIMIT)
    await ctx.send(embed=embed)

@bot.command(name="czas-miesiac", aliases=["czas-miesiąc"])
@has_stats_role()
async def stats_month(ctx):
    rows  = await db.get_stats(period="month")
    embed = fmt.build_embed(rows, "📆 Aktywność – ostatnie 30 dni", discord.Color.green(), limit=EMBED_RANK_LIMIT)
    await ctx.send(embed=embed)

@bot.command(name="czas-kwartal", aliases=["czas-kwartał"])
@has_stats_role()
async def stats_quarter(ctx):
    rows  = await db.get_stats(period="quarter")
    embed = fmt.build_embed(rows, "📊 Aktywność – ostatnie 3 miesiące", discord.Color.orange(), limit=EMBED_RANK_LIMIT)
    await ctx.send(embed=embed)

@bot.command(name="czas-alltime")
@has_stats_role()
async def stats_alltime(ctx):
    rows  = await db.get_stats(period="alltime")
    embed = fmt.build_embed(rows, "🏆 Aktywność – wszystkie czasy", discord.Color.gold(), limit=EMBED_RANK_LIMIT)
    await ctx.send(embed=embed)

@bot.command(name="czas-afazja")
@has_stats_role()
async def stats_special(ctx):
    if SPECIAL_CHANNEL_ID == 0:
        await ctx.send("❌ Specjalny kanał nie jest skonfigurowany.")
        return
    rows  = await db.get_special_stats()
    embed = fmt.build_embed(rows, "🎉 Afazja – Pt/Sb 20:00–06:00 (all time)", discord.Color.purple(), limit=EMBED_RANK_LIMIT)
    await ctx.send(embed=embed)

@bot.command(name="czas-kto")
@has_stats_role()
async def stats_user(ctx, *, member: discord.Member = None):
    target = member or ctx.author
    rows   = await db.get_user_stats(target.id)
    embed  = fmt.build_user_embed(rows, target.display_name)
    await ctx.send(embed=embed)

class InactiveReportView(discord.ui.View):
    """Paginacja dla !czas-nieaktywni – jednorazowa (timeout), bo to raport
    na żądanie, w przeciwieństwie do stałych raportów miesięcznych/kwartalnych
    (te używają ReportButton, które przetrwa restart bota)."""

    def __init__(self, entries: list[dict], ranks: dict, min_days: int, page: int = 0):
        super().__init__(timeout=180)
        self.entries  = entries
        self.ranks    = ranks
        self.min_days = min_days
        self.page     = page
        self._sync_buttons()

    def _build(self):
        return fmt.build_list_embed(
            f"😴 Nieaktywni {self.min_days}+ dni", self.entries, self.page,
            REPORT_PAGE_SIZE, self.ranks, "inactive", discord.Color.red())

    def _sync_buttons(self):
        self.clear_items()
        _, total_pages, _ = self._build()
        if self.page > 0:
            self.add_item(self._make_button("◀", -1))
        if self.page < total_pages - 1:
            self.add_item(self._make_button("▶", 1))

    def _make_button(self, label: str, delta: int):
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)

        async def callback(interaction: discord.Interaction):
            self.page += delta
            embed, _, self.page = self._build()
            self._sync_buttons()
            await interaction.response.edit_message(embed=embed, view=self)

        button.callback = callback
        return button

    async def on_timeout(self):
        self.clear_items()

@bot.command(name="czas-nieaktywni", aliases=["czas-nieaktywni-3m"])
@has_stats_role()
async def stats_inactive(ctx, dni: int = 90):
    """Raport osób nieaktywnych od co najmniej `dni` dni (domyślnie 90 = 3 miesiące).
    W tym osoby, które nigdy nie były aktywne na kanałach głosowych.
    Użycie: !czas-nieaktywni [liczba_dni]
    """
    guild = _get_main_guild()
    if not guild:
        await ctx.send("❌ Nie mogę odnaleźć głównego serwera.")
        return
    dni = max(1, dni)
    entries = await _get_long_inactive_members(guild, dni)
    ranks   = await _get_ranks_map()
    view    = InactiveReportView(entries, ranks, dni)
    embed, _, _ = view._build()
    await ctx.send(embed=embed, view=view)

@bot.command(name="test-raport")
@commands.has_permissions(administrator=True)
async def test_raport(ctx, typ: str = None):
    """Wysyła raport miesięczny i/lub kwartalny natychmiast, na kanał REPORT_CHANNEL_ID.
    Użycie: !test-raport miesiac | !test-raport kwartal | !test-raport (oba)
    """
    if REPORT_CHANNEL_ID == 0:
        await ctx.send("❌ `REPORT_CHANNEL_ID` nie jest skonfigurowany w Railway.")
        return

    typ = (typ or "").lower()
    if typ in ("miesiac", "miesiąc", "monthly"):
        await _send_monthly_report()
    elif typ in ("kwartal", "kwartał", "quarterly"):
        await _send_quarterly_report()
    else:
        await _send_monthly_report()
        await _send_quarterly_report()

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
        ("!czas-nieaktywni [dni]", "Raport nieaktywnych – domyślnie 90 dni (3 mies.)"),
        ("!pomoc",            "Ta wiadomość"),
        ("!test-raport [miesiac|kwartal]", "Wyślij raport od razu (admin)"),
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
        except (discord.Forbidden, discord.NotFound):
            pass  # brak uprawnień albo wiadomość już usunięta – oba przypadki bezpiecznie ignorujemy
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Nie znalazłem takiego użytkownika.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # literówka w komendzie – nie zaśmiecamy logów
    else:
        print(f"Błąd komendy: {error}")

# ── HTTP API dla dashboardu ────────────────────────────────────────────────────

def _auth(request: web.Request) -> bool:
    if not DASHBOARD_API_ENABLED:
        return False
    provided = request.headers.get("Authorization", "")
    expected = f"Bearer {DASHBOARD_SECRET}"
    return hmac.compare_digest(provided, expected)

def _guard(request: web.Request):
    """Zwraca gotową odpowiedź błędu albo None jeśli można obsłużyć zapytanie.

    Rozdziela trzy przypadki, które wcześniej dawały mylące 401/500:
      503 – API wyłączone (brak DASHBOARD_SECRET) lub baza jeszcze nie wstała
      401 – zły/brakujący token
    """
    if not DASHBOARD_API_ENABLED:
        return web.json_response({"error": "API wyłączone – brak DASHBOARD_SECRET"}, status=503)
    if not _auth(request):
        return web.Response(status=401)
    if db.pool is None:
        return web.json_response({"error": "Bot się uruchamia – baza jeszcze niegotowa"}, status=503)
    return None

def _json(data) -> web.Response:
    return web.Response(
        text=json.dumps(data, ensure_ascii=False, default=str),
        content_type="application/json"
    )

async def api_stats(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_stats(period=request.match_info.get("period", "week")))

async def api_special(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_special_stats())

async def api_reports(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_report_log())

async def api_inactive(request):
    err = _guard(request)
    if err: return err
    members = await _get_inactive_members()
    return _json([{"display_name": m.display_name,
                   "joined_at": m.joined_at.isoformat() if m.joined_at else None}
                  for m in members])

async def api_role_grants(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_role_grants())

async def api_activity_chart(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_daily_activity(days=30))

async def api_online(request):
    err = _guard(request)
    if err: return err
    now = datetime.utcnow()
    return _json([{
        "user_id":      uid,
        "display_name": s["display_name"],
        "channel_name": s["channel_name"],
        "elapsed_s":    int((now - s["joined"]).total_seconds()),
        "is_special":   s.get("is_special", False),
    } for uid, s in tracker.active.items()])

def _rank_for_member(member: discord.Member, role_brojler, role_opierzony) -> str:
    """Pomocnicza funkcja – wyznacza rangę na podstawie posiadanych ról."""
    member_role_ids = {r.id for r in member.roles}
    if role_brojler and role_brojler.id in member_role_ids:
        return "BROJLER"
    if role_opierzony and role_opierzony.id in member_role_ids:
        return "OPIERZONY"
    return "PISKLAK"

# Cache w pamięci (60s) – żeby dashboard i checkery powiadomień nie zasypywały
# Discord API osobnymi zapytaniami fetch_members przy każdym odświeżeniu/godzinie.
_member_roles_cache = {"data": None, "fetched_at": 0.0}
MEMBER_ROLES_CACHE_TTL = 60  # sekundy

async def _get_all_members_ranked(force_refresh: bool = False) -> dict:
    """Zwraca {user_id_str: {"display_name":..., "rank":...}} z JEDYNEGO głównego serwera, z cache."""
    now_ts = time.monotonic()
    if not force_refresh and _member_roles_cache["data"] is not None and \
       (now_ts - _member_roles_cache["fetched_at"]) < MEMBER_ROLES_CACHE_TTL:
        return _member_roles_cache["data"]

    result = {}
    guild = _get_main_guild()
    if guild:
        role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
        role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
        try:
            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue
                result[str(member.id)] = {
                    "display_name": member.display_name,
                    "rank": _rank_for_member(member, role_brojler, role_opierzony),
                }
        except Exception as e:
            print(f"fetch_members error: {e}")
            for member in guild.members:
                if member.bot:
                    continue
                result[str(member.id)] = {
                    "display_name": member.display_name,
                    "rank": _rank_for_member(member, role_brojler, role_opierzony),
                }

    _member_roles_cache["data"]       = result
    _member_roles_cache["fetched_at"] = now_ts
    return result

# ── Migawka członków – zakładka "Lista aktywności" ──────────────────────────
# Osobny task (nie dokładamy do threshold_and_stale_checker) – ten ma lecieć
# także w quiet hours, bo dashboard powinien mieć świeże dane niezależnie od
# okna 8:00–22:00 używanego przez powiadomienia.

async def _build_member_snapshot_rows() -> list[tuple]:
    guild = _get_main_guild()
    if not guild:
        return []
    role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
    role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
    # Świeże dane, nie cache 60s – task leci raz na godzinę, więc nie ma co
    # oszczędzać na tym jednym zapytaniu.
    last_activity = await db.get_last_activity_per_user()
    now = datetime.now(timezone.utc)

    try:
        members = [m async for m in guild.fetch_members(limit=None) if not m.bot]
    except Exception as e:
        print(f"⚠️  member_snapshot_task – fetch_members error: {e}")
        members = [m for m in guild.members if not m.bot]

    rows = []
    for member in members:
        last_seen = last_activity.get(str(member.id))
        days_inactive = None if last_seen is None else (now - last_seen).days
        rows.append((
            member.id,
            member.display_name,
            member.name,
            _rank_for_member(member, role_brojler, role_opierzony),
            member.joined_at,
            last_seen,
            days_inactive,
        ))
    return rows

@tasks.loop(hours=1)
async def member_snapshot_task():
    try:
        rows = await _build_member_snapshot_rows()
        if rows:
            await db.save_member_snapshot(rows)
    except Exception as e:
        print(f"⚠️  member_snapshot_task – błąd: {e}")

async def api_debug_roles(request):
    """Diagnostyka – pokazuje surowe dane o rangach, żeby namierzyć rozbieżności."""
    err = _guard(request)
    if err: return err
    debug = {
        "ROLE_BROJLER_ID_z_konfiguracji":   ROLE_BROJLER_ID,
        "ROLE_OPIERZONY_ID_z_konfiguracji": ROLE_OPIERZONY_ID,
        "guilds": []
    }
    for guild in bot.guilds:
        role_brojler   = guild.get_role(ROLE_BROJLER_ID)   if ROLE_BROJLER_ID   else None
        role_opierzony = guild.get_role(ROLE_OPIERZONY_ID) if ROLE_OPIERZONY_ID else None
        guild_info = {
            "guild_name": guild.name,
            "guild_id": guild.id,
            "rola_BROJLER_znaleziona_na_serwerze":   role_brojler.name   if role_brojler   else None,
            "rola_OPIERZONY_znaleziona_na_serwerze": role_opierzony.name if role_opierzony else None,
            "liczba_wszystkich_rol_na_serwerze": len(guild.roles),
            "wszystkie_role_BROJLER_na_serwerze": [
                {"id": r.id, "name": r.name} for r in guild.roles if "BROJLER" in r.name.upper()
            ],
            "wszystkie_role_OPIERZONY_na_serwerze": [
                {"id": r.id, "name": r.name} for r in guild.roles if "OPIERZONY" in r.name.upper()
            ],
            "members": [],
        }
        try:
            member_count = 0
            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue
                member_count += 1
                guild_info["members"].append({
                    "display_name": member.display_name,
                    "user_id": str(member.id),
                    "is_owner": member.id == guild.owner_id,
                    "wszystkie_role_membera": [{"id": r.id, "name": r.name} for r in member.roles if r.name != "@everyone"],
                    "ma_role_brojler_wedlug_ID": bool(role_brojler and role_brojler.id in {r.id for r in member.roles}),
                })
            guild_info["fetch_members_pobral_osob"] = member_count
        except Exception as e:
            guild_info["fetch_members_blad"] = str(e)
        debug["guilds"].append(guild_info)
    return _json(debug)

async def api_member_roles(request):
    """Zwraca rangę każdego membera – świeże dane z Discord API, cache 60s."""
    err = _guard(request)
    if err: return err
    return _json(await _get_all_members_ranked())

async def api_monthly_activity(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_monthly_activity())

async def api_weekly_activity(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_weekly_activity())

async def api_records(request):
    err = _guard(request)
    if err: return err
    return _json(await db.get_records())

# Cache dla ostatniej aktywności (60s) – to samo obciążenie DB co
# _member_roles_cache, ale dla osobnego, dość ciężkiego zapytania GROUP BY.
_last_activity_cache = {"data": None, "fetched_at": 0.0}
LAST_ACTIVITY_CACHE_TTL = 60  # sekundy

async def _get_last_activity_cached() -> dict:
    now_ts = time.monotonic()
    if _last_activity_cache["data"] is not None and \
       (now_ts - _last_activity_cache["fetched_at"]) < LAST_ACTIVITY_CACHE_TTL:
        return _last_activity_cache["data"]
    data = await db.get_last_activity_per_user()
    _last_activity_cache["data"]       = data
    _last_activity_cache["fetched_at"] = now_ts
    return data

async def api_activity_list(request):
    """Migawka wszystkich członków dla zakładki 'Lista aktywności' – czytana
    z tabeli member_snapshot (odświeżanej co godzinę), nie z Discorda na żywo."""
    err = _guard(request)
    if err: return err
    return _json(await db.get_member_snapshot())

async def api_stale_ranked(request):
    """Osoby z rangą OPIERZONY/BROJLER nieaktywne od ponad STALE_DAYS dni."""
    err = _guard(request)
    if err: return err

    last_activity = await _get_last_activity_cached()
    now = datetime.now(timezone.utc)
    ranked = await _get_all_members_ranked()  # korzysta ze wspólnego cache 60s
    result = []

    for user_id_str, info in ranked.items():
        rank = info["rank"]
        if rank == "PISKLAK":
            continue  # PISKLAK nie interesuje nas tutaj

        last_seen = last_activity.get(user_id_str)
        if last_seen is None:
            days_inactive = None  # nigdy nie widziany na kanale
        else:
            days_inactive = (now - last_seen).days

        if days_inactive is None or days_inactive >= STALE_DAYS:
            result.append({
                "display_name":  info["display_name"],
                "rank":          rank,
                "last_seen":     last_seen.isoformat() if last_seen else None,
                "days_inactive": days_inactive,
            })

    result.sort(key=lambda r: (r["days_inactive"] is None, r["days_inactive"] or 0), reverse=True)
    return _json(result)

async def api_server_stats(request):
    err = _guard(request)
    if err: return err
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
    """Health-check. Bez tokenu zwraca sam status (dla UptimeRobota itp.),
    pełne dane diagnostyczne tylko po autoryzacji – wcześniej nazwa bota,
    liczba serwerów, uptime i opóźnienia bazy były publiczne."""
    uptime_s = time.monotonic() - BOT_START_TIME

    # Sprawdź żywotność połączenia z bazą prostym zapytaniem
    db_connected = False
    db_latency_ms = None
    if db.pool is not None:
        try:
            t0 = time.monotonic()
            async with db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_latency_ms = round((time.monotonic() - t0) * 1000, 1)
            db_connected = True
        except Exception as e:
            print(f"health-check: błąd bazy – {e}")

    status = "ok" if db_connected else "degraded"
    if not _auth(request):
        return _json({"status": status})  # publiczne minimum

    return _json({
        "status":                status,
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
    if DEBUG_ENDPOINTS:
        # Pełny zrzut członków z rolami – rejestrowany tylko na żądanie,
        # żeby nie trzymać stale otwartego endpointu z danymi całego serwera.
        app.router.add_get("/api/debug-roles",  api_debug_roles)
        print("⚠️  /api/debug-roles WŁĄCZONY (DEBUG_ENDPOINTS=1) – wyłącz po diagnozie.")
    app.router.add_get("/api/monthly-activity", api_monthly_activity)
    app.router.add_get("/api/weekly-activity",  api_weekly_activity)
    app.router.add_get("/api/records",          api_records)
    app.router.add_get("/api/server-stats",     api_server_stats)
    app.router.add_get("/api/stale-ranked",     api_stale_ranked)
    app.router.add_get("/api/activity-list",    api_activity_list)
    return app

async def _flush_on_shutdown():
    """Przy redeployu Railway wysyła SIGTERM. Bez tego trwające sesje traciły
    czas od ostatniego checkpointu (do 5 minut na osobę)."""
    try:
        await tracker.flush_active(datetime.now(timezone.utc))
        print("💾  Zapisano trwające sesje przed wyłączeniem.")
    except Exception as e:
        print(f"⚠️  Nie udało się zapisać sesji przed wyłączeniem: {e}")

async def main():
    app    = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site   = web.TCPSite(runner, "0.0.0.0", DASHBOARD_PORT)
    await site.start()

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows – pomijamy

    async with bot:
        bot_task = asyncio.create_task(bot.start(TOKEN))
        done, _ = await asyncio.wait(
            [bot_task, asyncio.create_task(stop.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if bot_task not in done:
            await _flush_on_shutdown()
            bot_task.cancel()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
