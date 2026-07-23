"""
stats.py – formatowanie statystyk do Discord Embeds.
"""

import io
import csv
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

    def build_csv(self, rows: list[dict], filename: str) -> discord.File:
        """Generuje plik CSV w pamięci ze WSZYSTKIMI wierszami (nie tylko top N z embeda)."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Pozycja", "Użytkownik", "Czas (sekundy)", "Czas"])
        for i, row in enumerate(rows, start=1):
            name = row.get("display_name") or f"ID:{row.get('user_id')}"
            secs = int(row.get("total_seconds") or 0)
            writer.writerow([i, name, secs, _fmt_time(secs)])
        data = buf.getvalue().encode("utf-8-sig")  # BOM – poprawne polskie znaki w Excelu
        return discord.File(io.BytesIO(data), filename=filename)

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
