"""
database.py – obsługa PostgreSQL na Railway.
Railway oferuje PostgreSQL jako natywną bazę danych.
Connection string pochodzi ze zmiennej środowiskowej DATABASE_URL.
"""

import os
import asyncpg
from datetime import datetime, timedelta

class Database:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL", "")
        self.pool: asyncpg.Pool | None = None

    async def init(self):
        self.pool = await asyncpg.create_pool(self.db_url, min_size=2, max_size=10)
        await self._create_tables()
        print("✅  PostgreSQL połączony i tabele gotowe.")

    async def _create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS voice_sessions (
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     BIGINT      NOT NULL,
                    display_name TEXT       NOT NULL,
                    channel_id  BIGINT      NOT NULL,
                    channel_name TEXT       NOT NULL,
                    joined_at   TIMESTAMPTZ NOT NULL,
                    left_at     TIMESTAMPTZ,
                    duration_s  INTEGER,          -- NULL gdy sesja trwa
                    is_special  BOOLEAN DEFAULT FALSE
                );

                CREATE INDEX IF NOT EXISTS idx_vs_user   ON voice_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_vs_joined ON voice_sessions(joined_at);
                CREATE INDEX IF NOT EXISTS idx_vs_special ON voice_sessions(is_special);
            """)

    # ── Zapis sesji ──────────────────────────────────────────────────────────

    async def open_session(self, user_id: int, display_name: str,
                           channel_id: int, channel_name: str,
                           joined_at: datetime, is_special: bool) -> int:
        """Tworzy nowy rekord sesji i zwraca jej ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO voice_sessions
                    (user_id, display_name, channel_id, channel_name, joined_at, is_special)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, user_id, display_name, channel_id, channel_name, joined_at, is_special)
            return row["id"]

    async def close_session(self, session_id: int, left_at: datetime, duration_s: int,
                            display_name: str):
        """Zamyka sesję i zapisuje czas trwania. Aktualizuje też nick."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE voice_sessions
                SET left_at = $1, duration_s = $2, display_name = $3
                WHERE id = $4
            """, left_at, duration_s, display_name, session_id)

    async def update_session_checkpoint(self, session_id: int, display_name: str,
                                        checkpoint: datetime, duration_so_far: int):
        """Aktualizuje trwającą sesję (checkpoint co 5 min) – nie zamyka jej."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE voice_sessions
                SET display_name = $1, duration_s = $2
                WHERE id = $3 AND left_at IS NULL
            """, display_name, duration_so_far, session_id)

    # ── Statystyki ────────────────────────────────────────────────────────────

    async def get_stats(self, period: str) -> list[dict]:
        """
        Zwraca ranking użytkowników wg łącznego czasu na kanałach głosowych.
        period: 'week' | 'month' | 'halfyear' | 'alltime'
        """
        cutoff_map = {
            "week":     "NOW() - INTERVAL '7 days'",
            "month":    "NOW() - INTERVAL '30 days'",
            "halfyear": "NOW() - INTERVAL '180 days'",
            "alltime":  "TO_TIMESTAMP(0)",
        }
        cutoff_expr = cutoff_map.get(period, "TO_TIMESTAMP(0)")

        query = f"""
            SELECT
                user_id,
                -- Najnowszy nick użytkownika
                (SELECT display_name FROM voice_sessions v2
                 WHERE v2.user_id = vs.user_id
                 ORDER BY joined_at DESC LIMIT 1)  AS display_name,
                SUM(COALESCE(duration_s, 0))        AS total_seconds
            FROM voice_sessions vs
            WHERE joined_at >= {cutoff_expr}
              AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
            GROUP BY user_id
            ORDER BY total_seconds DESC
            LIMIT 25
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def get_special_stats(self) -> list[dict]:
        """Statystyki tylko ze specjalnego kanału (is_special = TRUE)."""
        query = """
            SELECT
                user_id,
                (SELECT display_name FROM voice_sessions v2
                 WHERE v2.user_id = vs.user_id
                 ORDER BY joined_at DESC LIMIT 1)  AS display_name,
                SUM(COALESCE(duration_s, 0))        AS total_seconds
            FROM voice_sessions vs
            WHERE is_special = TRUE
              AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
            GROUP BY user_id
            ORDER BY total_seconds DESC
            LIMIT 25
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [dict(r) for r in rows]

    async def get_user_stats(self, user_id: int) -> list[dict]:
        """Szczegółowe statystyki jednej osoby (4 okresy + specjalny)."""
        periods = [
            ("Ostatnie 7 dni",     "NOW() - INTERVAL '7 days'"),
            ("Ostatnie 30 dni",    "NOW() - INTERVAL '30 days'"),
            ("Ostatnie 6 miesięcy","NOW() - INTERVAL '180 days'"),
            ("Wszystkie czasy",    "TO_TIMESTAMP(0)"),
        ]
        results = []
        async with self.pool.acquire() as conn:
            # Nick z ostatniej sesji
            nick_row = await conn.fetchrow("""
                SELECT display_name FROM voice_sessions
                WHERE user_id = $1 ORDER BY joined_at DESC LIMIT 1
            """, user_id)
            display_name = nick_row["display_name"] if nick_row else str(user_id)

            for label, cutoff in periods:
                row = await conn.fetchrow(f"""
                    SELECT SUM(COALESCE(duration_s, 0)) AS total_seconds,
                           COUNT(*) AS sessions
                    FROM voice_sessions
                    WHERE user_id = $1 AND joined_at >= {cutoff}
                      AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                """, user_id)
                results.append({
                    "label": label,
                    "display_name": display_name,
                    "total_seconds": row["total_seconds"] or 0,
                    "sessions": row["sessions"] or 0,
                })

            # Specjalny kanał
            special_row = await conn.fetchrow("""
                SELECT SUM(COALESCE(duration_s, 0)) AS total_seconds,
                       COUNT(*) AS sessions
                FROM voice_sessions
                WHERE user_id = $1 AND is_special = TRUE
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
            """, user_id)
            results.append({
                "label": "🎉 Specjalny kanał (Pt/Sb 20–02)",
                "display_name": display_name,
                "total_seconds": special_row["total_seconds"] or 0,
                "sessions": special_row["sessions"] or 0,
            })

        return results
