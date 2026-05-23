"""
stats.py – formatowanie statystyk do Discord Embeds.
"""

import discord
from datetime import timedelta


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


MEDALS = ["🥇", "🥈", "🥉"]


class StatsFormatter:

    def build_embed(self, rows: list[dict], title: str, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(title=title, color=color)

        if not rows:
            embed.description = "Brak danych za ten okres. 📭"
            return embed

        lines = []
        for i, row in enumerate(rows):
            pos    = MEDALS[i] if i < 3 else f"`{i+1:>2}.`"
            name   = row.get("display_name") or f"<@{row['user_id']}>"
            secs   = row.get("total_seconds") or 0
            time_s = _fmt_time(int(secs))
            lines.append(f"{pos} **{name}** – {time_s}")

        embed.description = "\n".join(lines)
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
