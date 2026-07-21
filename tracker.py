"""
tracker.py – śledzenie sesji głosowych w pamięci + zapis do bazy.

Specjalny kanał: zliczany TYLKO gdy jest aktywne okno:
  - Piątek (weekday=4) lub Sobota (weekday=5)
  - godzina lokalna 20:00–23:59 LUB 00:00–06:00

Bot pracuje w UTC; konwersja do strefy PL (UTC+1 / UTC+2) przez env TIMEZONE.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from database import Database

TZ_NAME = os.getenv("TIMEZONE", "Europe/Warsaw")
LOCAL_TZ = ZoneInfo(TZ_NAME)


def _is_special_window(dt_utc: datetime) -> bool:
    """Sprawdza czy chwila UTC mieści się w oknie Pt/Sb 20:00–06:00 (czas lokalny)."""
    local = dt_utc.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    wd = local.weekday()   # 0=Pon … 4=Pt 5=Sb 6=Nd
    h  = local.hour

    # Piątek 20–23
    if wd == 4 and h >= 20:
        return True
    # Sobota 00–05 (noc z piątku) oraz 20–23
    if wd == 5 and (h < 6 or h >= 20):
        return True
    # Niedziela 00–05 (noc z soboty)
    if wd == 6 and h < 6:
        return True
    return False


class VoiceTracker:
    """
    active: {user_id: {
        session_id, channel_id, channel_name, display_name,
        joined, is_special
    }}
    """

    def __init__(self, db: Database, special_channel_id: int):
        self.db = db
        self.special_channel_id = special_channel_id
        self.active: dict[int, dict] = {}

    def join(self, user_id: int, display_name: str,
             channel_id: int, channel_name: str, now: datetime):
        """Rejestruje dołączenie użytkownika do kanału (in-memory)."""
        is_special = (
            channel_id == self.special_channel_id
            and _is_special_window(now)
        )
        self.active[user_id] = {
            "session_id":    None,   # wypełniamy async
            "channel_id":   channel_id,
            "channel_name": channel_name,
            "display_name": display_name,
            "joined":       now,
            "is_special":   is_special,
            "_pending_open": True,
        }
        import asyncio
        asyncio.create_task(self._open_db_session(user_id, now))

    async def _open_db_session(self, user_id: int, now: datetime):
        if user_id not in self.active:
            return
        sess = self.active[user_id]
        sid = await self.db.open_session(
            user_id, sess["display_name"],
            sess["channel_id"], sess["channel_name"],
            now, sess["is_special"],
        )
        if user_id in self.active:
            self.active[user_id]["session_id"] = sid
            self.active[user_id]["_pending_open"] = False

    async def leave(self, user_id: int, channel_id: int, now: datetime):
        """Rejestruje opuszczenie kanału i zapisuje sesję."""
        sess = self.active.pop(user_id, None)
        if not sess:
            return

        duration_s = max(0, int((now - sess["joined"]).total_seconds()))

        # Jeśli sesja jeszcze się otwiera w bazie – poczekaj aż session_id
        # faktycznie się pojawi (zamiast zgadywać po jednym stałym sleepie).
        if sess.get("_pending_open"):
            import asyncio
            for _ in range(20):  # maks. ~5s (20 × 0.25s)
                # Sprawdź czy w międzyczasie ten sam user wrócił na kanał
                # (np. szybkie przełączenie) – wtedy nie zamykamy jego nowej sesji
                if user_id in self.active and self.active[user_id]["joined"] != sess["joined"]:
                    return
                if sess.get("session_id"):
                    break
                await asyncio.sleep(0.25)

        if sess.get("session_id"):
            await self.db.close_session(
                sess["session_id"], now, duration_s, sess["display_name"]
            )
        else:
            # Sesja nigdy nie zdążyła się otworzyć w bazie (bardzo wolna odpowiedź DB)
            # – zapisz ją teraz od razu jako zamkniętą, żeby nie stracić czasu.
            print(f"⚠️  Sesja user_id={user_id} nie miała session_id – zapisuję awaryjnie.")
            new_id = await self.db.open_session(
                user_id, sess["display_name"], sess["channel_id"], sess["channel_name"],
                sess["joined"], sess["is_special"],
            )
            await self.db.close_session(new_id, now, duration_s, sess["display_name"])

    async def flush_active(self, now: datetime):
        """
        Co 5 minut: aktualizuje duration_s dla trwających sesji
        (checkpoint – nie zamyka ich).
        """
        for uid, sess in list(self.active.items()):
            if sess.get("session_id") and not sess.get("_pending_open"):
                elapsed = max(0, int((now - sess["joined"]).total_seconds()))
                await self.db.update_session_checkpoint(
                    sess["session_id"], sess["display_name"], now, elapsed
                )
