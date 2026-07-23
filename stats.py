"""
stats.py – formatowanie statystyk do Discord Embeds.
"""

import discord

def _fmt_time(seconds: int) -> str:
    """Zamienia sekundy na czytelny format hh:mm lub Xh Ym."""
    if seconds <= 0:
        return "0 min"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h == 0:
        return f"{m} min"
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}min"


class StatsFormatter:

    def build_embed(self, rows: list[dict], title: str, color: discord.Color, limit: int | None = None) -> discord.Embed:
        """Używane przez interaktywne komendy (!czas-tydzień itd.)."""
        embed = discord.Embed(title=title, color=color)

        if not rows:
            embed.description = "Brak danych za ten okres."
            return embed

        display_rows = rows[:limit] if limit else rows

        lines = []
        for i, row in enumerate(display_rows):
            name   = row.get("display_name") or f"<@{row['user_id']}>"
            secs   = row.get("total_seconds") or 0
            time_s = _fmt_time(int(secs))
            lines.append(f"{i+1}. **{name}** – {time_s}")

        embed.description = "\n".join(lines)
        if limit and len(rows) > limit:
            embed.set_footer(text=f"Top {len(display_rows)} z {len(rows)} aktywnych osób")
        else:
            embed.set_footer(text=f"Łącznie {len(rows)} osób")
        return embed

    def build_user_embed(self, rows: list[dict], display_name: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"📋 Statystyki – {display_name}",
            color=discord.Color.blurple()
        )
        if not rows:
            embed.description = "Brak danych dla tego użytkownika."
            return embed

        for row in rows:
            secs     = row.get("total_seconds") or 0
            sessions = row.get("sessions") or 0
            val = f"⏱️ **{_fmt_time(int(secs))}** ({sessions} sesji)"
            embed.add_field(name=row["label"], value=val, inline=False)

        return embed

    # ── Nowy format raportów miesięcznych/kwartalnych (strona statystyk) ────────

    def build_summary_embed(self, title: str, summary: dict, color: discord.Color) -> discord.Embed:
        """Strona 1 raportu – zbiorcze statystyki w formie kart (pól embeda),
        nie listy punktowanej."""
        embed = discord.Embed(title=title, color=color)

        embed.add_field(name="Łącznie aktywnych", value=str(summary["active_users"]), inline=True)
        embed.add_field(name="Łączny czas", value=_fmt_time(summary["total_seconds"]), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer – wyrównanie do 3 kolumn

        ls = summary.get("longest_session")
        embed.add_field(
            name="Najdłuższa sesja",
            value=f"{_fmt_time(ls['duration_s'])} – {ls['display_name']}" if ls else "brak danych",
            inline=True,
        )
        bd = summary.get("best_day")
        embed.add_field(
            name="Najlepszy dzień",
            value=f"{_fmt_time(bd['total_seconds'])} – {bd['day'].strftime('%d.%m')}" if bd else "brak danych",
            inline=True,
        )
        ak = summary.get("afazja_king")
        embed.add_field(
            name="Król Afazji",
            value=f"{ak['display_name']} – {_fmt_time(ak['total_seconds'])}" if ak else "brak danych",
            inline=True,
        )
        return embed

    # ── Nowy format raportów – paginowane listy Aktywni / Nieaktywni ───────────

    def build_list_embed(self, title: str, entries: list[dict], page: int, per_page: int,
                          ranks: dict, mode: str, color: discord.Color):
        """Zwraca (embed, total_pages, faktyczna_strona).

        entries dla mode="active":   [{display_name, user_id, total_seconds}, ...]
        entries dla mode="inactive": [{display_name, user_id, days_inactive}, ...]
        ranks: {user_id_str: "BROJLER"|"OPIERZONY"|"PISKLAK"}
        """
        embed = discord.Embed(title=title, color=color)
        total_pages = max(1, (len(entries) + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        chunk = entries[page * per_page:(page + 1) * per_page]

        if not chunk:
            embed.description = "Brak danych."
        else:
            lines = []
            for i, e in enumerate(chunk, start=page * per_page + 1):
                rank = ranks.get(str(e.get("user_id", "")), "PISKLAK")
                rank_tag = f"`{rank}`"
                if mode == "active":
                    val = _fmt_time(int(e["total_seconds"]))
                else:
                    val = f"{e['days_inactive']} dni"
                lines.append(f"{i}. **{e['display_name']}** {rank_tag} – {val}")
            embed.description = "\n".join(lines)

        embed.set_footer(text=f"Strona {page+1} z {total_pages}")
        return embed, total_pages, page
