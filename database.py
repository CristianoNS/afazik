"""
database.py – obsługa PostgreSQL na Railway.
"""
import os
import asyncpg
from datetime import datetime

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
                    id           BIGSERIAL PRIMARY KEY,
                    user_id      BIGINT       NOT NULL,
                    display_name TEXT         NOT NULL,
                    channel_id   BIGINT       NOT NULL,
                    channel_name TEXT         NOT NULL,
                    joined_at    TIMESTAMPTZ  NOT NULL,
                    left_at      TIMESTAMPTZ,
                    duration_s   INTEGER,
                    is_special   BOOLEAN DEFAULT FALSE
                );
                CREATE INDEX IF NOT EXISTS idx_vs_user    ON voice_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_vs_joined  ON voice_sessions(joined_at);
                CREATE INDEX IF NOT EXISTS idx_vs_special ON voice_sessions(is_special);

                CREATE TABLE IF NOT EXISTS report_log (
                    id         BIGSERIAL PRIMARY KEY,
                    type       TEXT        NOT NULL,
                    sent_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    entry_count INTEGER
                );

                CREATE TABLE IF NOT EXISTS role_grants (
                    id           BIGSERIAL PRIMARY KEY,
                    user_id      BIGINT      NOT NULL,
                    display_name TEXT        NOT NULL,
                    role_name    TEXT        NOT NULL,
                    total_seconds INTEGER   NOT NULL,
                    granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)

    # ── Sesje ────────────────────────────────────────────────────────────────

    async def open_session(self, user_id, display_name, channel_id, channel_name, joined_at, is_special) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO voice_sessions (user_id, display_name, channel_id, channel_name, joined_at, is_special)
                VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
            """, user_id, display_name, channel_id, channel_name, joined_at, is_special)
            return row["id"]

    async def close_session(self, session_id, left_at, duration_s, display_name):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE voice_sessions SET left_at=$1, duration_s=$2, display_name=$3 WHERE id=$4
            """, left_at, duration_s, display_name, session_id)

    async def update_session_checkpoint(self, session_id, display_name, checkpoint, duration_so_far):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE voice_sessions SET display_name=$1, duration_s=$2
                WHERE id=$3 AND left_at IS NULL
            """, display_name, duration_so_far, session_id)

    # ── Statystyki ────────────────────────────────────────────────────────────

    async def get_stats(self, period: str) -> list[dict]:
        cutoff_map = {
            "week":    "NOW() - INTERVAL '7 days'",
            "month":   "NOW() - INTERVAL '30 days'",
            "quarter": "NOW() - INTERVAL '90 days'",
            "alltime": "TO_TIMESTAMP(0)",
        }
        cutoff = cutoff_map.get(period, "TO_TIMESTAMP(0)")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT CAST(user_id AS TEXT) AS user_id,
                    (SELECT display_name FROM voice_sessions v2
                     WHERE v2.user_id=vs.user_id ORDER BY joined_at DESC LIMIT 1) AS display_name,
                    SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions vs
                WHERE joined_at >= {cutoff}
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                GROUP BY user_id ORDER BY total_seconds DESC LIMIT 100
            """)
            return [dict(r) for r in rows]

    async def get_special_stats(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT CAST(user_id AS TEXT) AS user_id,
                    (SELECT display_name FROM voice_sessions v2
                     WHERE v2.user_id=vs.user_id ORDER BY joined_at DESC LIMIT 1) AS display_name,
                    SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions vs
                WHERE is_special=TRUE AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                GROUP BY user_id ORDER BY total_seconds DESC LIMIT 100
            """)
            return [dict(r) for r in rows]

    async def get_user_stats(self, user_id: int) -> list[dict]:
        periods = [
            ("Ostatnie 7 dni",      "NOW() - INTERVAL '7 days'"),
            ("Ostatnie 30 dni",     "NOW() - INTERVAL '30 days'"),
            ("Ostatnie 3 miesiące", "NOW() - INTERVAL '90 days'"),
            ("Wszystkie czasy",     "TO_TIMESTAMP(0)"),
        ]
        results = []
        async with self.pool.acquire() as conn:
            nick = await conn.fetchrow(
                "SELECT display_name FROM voice_sessions WHERE user_id=$1 ORDER BY joined_at DESC LIMIT 1", user_id)
            dn = nick["display_name"] if nick else str(user_id)
            for label, cutoff in periods:
                row = await conn.fetchrow(f"""
                    SELECT SUM(COALESCE(duration_s,0)) AS total_seconds, COUNT(*) AS sessions
                    FROM voice_sessions
                    WHERE user_id=$1 AND joined_at>={cutoff}
                      AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                """, user_id)
                results.append({"label": label, "display_name": dn,
                                "total_seconds": row["total_seconds"] or 0,
                                "sessions": row["sessions"] or 0})
            sp = await conn.fetchrow("""
                SELECT SUM(COALESCE(duration_s,0)) AS total_seconds, COUNT(*) AS sessions
                FROM voice_sessions WHERE user_id=$1 AND is_special=TRUE
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
            """, user_id)
            results.append({"label": "🎉 Kanał Afazja (Pt/Sb 20–06)", "display_name": dn,
                            "total_seconds": sp["total_seconds"] or 0,
                            "sessions": sp["sessions"] or 0})
        return results

    async def get_all_voice_user_ids(self) -> set[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT user_id FROM voice_sessions")
            return {r["user_id"] for r in rows}

    async def get_daily_activity(self, days: int = 30) -> list[dict]:
        """Aktywność dzienna (suma sekund) z ostatnich N dni – do wykresu."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT DATE(joined_at AT TIME ZONE 'Europe/Warsaw') AS day,
                       SUM(COALESCE(duration_s, 0)) AS total_seconds,
                       COUNT(DISTINCT user_id) AS unique_users
                FROM voice_sessions
                WHERE joined_at >= NOW() - INTERVAL '{days} days'
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                GROUP BY day ORDER BY day ASC
            """)
            return [dict(r) for r in rows]

    # ── Logi raportów i rang ──────────────────────────────────────────────────

    async def log_report(self, report_type: str, entry_count: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO report_log (type, entry_count) VALUES ($1, $2)",
                report_type, entry_count)

    async def get_report_log(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM report_log ORDER BY sent_at DESC LIMIT 50")
            return [dict(r) for r in rows]

    async def log_role_grant(self, user_id: int, display_name: str, role_name: str, total_seconds: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO role_grants (user_id, display_name, role_name, total_seconds)
                VALUES ($1,$2,$3,$4)
            """, user_id, display_name, role_name, total_seconds)


    async def get_monthly_activity(self, months: int = 12) -> list[dict]:
        """Aktywność miesięczna – do wykresu porównawczego."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT
                    TO_CHAR(DATE_TRUNC('month', joined_at AT TIME ZONE 'Europe/Warsaw'), 'YYYY-MM') AS month,
                    SUM(COALESCE(duration_s, 0)) AS total_seconds,
                    COUNT(DISTINCT user_id) AS unique_users
                FROM voice_sessions
                WHERE joined_at >= NOW() - INTERVAL '{months} months'
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                GROUP BY DATE_TRUNC('month', joined_at AT TIME ZONE 'Europe/Warsaw')
                ORDER BY 1 ASC
            """)
            return [dict(r) for r in rows]

    async def get_weekly_activity(self, weeks: int = 8) -> list[dict]:
        """Aktywność tygodniowa – do wykresu porównawczego."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT
                    TO_CHAR(DATE_TRUNC('week', joined_at AT TIME ZONE 'Europe/Warsaw'), 'YYYY-MM-DD') AS week,
                    SUM(COALESCE(duration_s, 0)) AS total_seconds,
                    COUNT(DISTINCT user_id) AS unique_users
                FROM voice_sessions
                WHERE joined_at >= NOW() - INTERVAL '{weeks} weeks'
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                GROUP BY DATE_TRUNC('week', joined_at AT TIME ZONE 'Europe/Warsaw')
                ORDER BY 1 ASC
            """)
            return [dict(r) for r in rows]

    async def get_records(self) -> dict:
        """Rekordy serwera."""
        async with self.pool.acquire() as conn:
            longest = await conn.fetchrow("""
                SELECT display_name, duration_s FROM voice_sessions
                WHERE duration_s IS NOT NULL ORDER BY duration_s DESC LIMIT 1
            """)
            best_day = await conn.fetchrow("""
                SELECT DATE(joined_at AT TIME ZONE 'Europe/Warsaw') AS day,
                       SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions WHERE left_at IS NOT NULL OR duration_s IS NOT NULL
                GROUP BY day ORDER BY total_seconds DESC LIMIT 1
            """)
            best_week = await conn.fetchrow("""
                SELECT DATE_TRUNC('week', joined_at AT TIME ZONE 'Europe/Warsaw') AS week,
                       SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions WHERE left_at IS NOT NULL OR duration_s IS NOT NULL
                GROUP BY week ORDER BY total_seconds DESC LIMIT 1
            """)
            leader = await conn.fetchrow("""
                SELECT (SELECT display_name FROM voice_sessions v2 WHERE v2.user_id=vs.user_id
                        ORDER BY joined_at DESC LIMIT 1) AS display_name,
                       SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions vs
                WHERE left_at IS NOT NULL OR duration_s IS NOT NULL
                GROUP BY user_id ORDER BY total_seconds DESC LIMIT 1
            """)
            afazja_leader = await conn.fetchrow("""
                SELECT (SELECT display_name FROM voice_sessions v2 WHERE v2.user_id=vs.user_id
                        ORDER BY joined_at DESC LIMIT 1) AS display_name,
                       SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions vs WHERE is_special=TRUE
                  AND (left_at IS NOT NULL OR duration_s IS NOT NULL)
                GROUP BY user_id ORDER BY total_seconds DESC LIMIT 1
            """)
            last_grant = await conn.fetchrow("""
                SELECT display_name, role_name, granted_at FROM role_grants
                ORDER BY granted_at DESC LIMIT 1
            """)
            return {
                "longest_session": dict(longest) if longest else None,
                "best_day":        dict(best_day) if best_day else None,
                "best_week":       dict(best_week) if best_week else None,
                "leader":          dict(leader) if leader else None,
                "afazja_leader":   dict(afazja_leader) if afazja_leader else None,
                "last_grant":      dict(last_grant) if last_grant else None,
            }

    async def get_server_stats(self) -> dict:
        """Zbiorcze statystyki serwera."""
        async with self.pool.acquire() as conn:
            total = await conn.fetchrow("""
                SELECT SUM(COALESCE(duration_s,0)) AS total_seconds,
                       COUNT(DISTINCT user_id) AS total_users
                FROM voice_sessions WHERE left_at IS NOT NULL OR duration_s IS NOT NULL
            """)
            best_day = await conn.fetchrow("""
                SELECT DATE(joined_at AT TIME ZONE 'Europe/Warsaw') AS day,
                       SUM(COALESCE(duration_s,0)) AS total_seconds
                FROM voice_sessions WHERE left_at IS NOT NULL OR duration_s IS NOT NULL
                GROUP BY day ORDER BY total_seconds DESC LIMIT 1
            """)
            dow = await conn.fetchrow("""
                SELECT EXTRACT(DOW FROM joined_at AT TIME ZONE 'Europe/Warsaw')::int AS dow,
                       AVG(daily_total) AS avg_seconds
                FROM (
                    SELECT DATE(joined_at AT TIME ZONE 'Europe/Warsaw') AS day,
                           EXTRACT(DOW FROM joined_at AT TIME ZONE 'Europe/Warsaw')::int AS dow,
                           SUM(COALESCE(duration_s,0)) AS daily_total
                    FROM voice_sessions WHERE left_at IS NOT NULL OR duration_s IS NOT NULL
                    GROUP BY day, dow
                ) d GROUP BY dow ORDER BY avg_seconds DESC LIMIT 1
            """)
            dow_names = ['Niedziela','Poniedziałek','Wtorek','Środa','Czwartek','Piątek','Sobota']
            ts = int(total["total_seconds"] or 0)
            tu = int(total["total_users"] or 0)
            return {
                "total_seconds":         ts,
                "total_users":           tu,
                "avg_seconds_per_user":  ts // max(1, tu),
                "best_day":              dict(best_day) if best_day else None,
                "most_active_dow":       dow_names[int(dow["dow"])] if dow else "–",
            }

    async def get_role_grants(self) -> list[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM role_grants ORDER BY granted_at DESC LIMIT 100")
            return [dict(r) for r in rows]
