# 🎙️ Discord Voice Tracker Bot – Afazja

Bot do zliczania czasu spędzonego na kanałach głosowych Discorda.
Działa 24/7 na Railway.com z bazą PostgreSQL i webowym dashboardem.

---

## 📋 Komendy

| Komenda | Opis | Dostęp |
|---|---|---|
| `!czas-tydzień` | Ranking aktywności z ostatnich 7 dni | Wyznaczona ranga |
| `!czas-miesiąc` | Ranking aktywności z ostatnich 30 dni | Wyznaczona ranga |
| `!czas-kwartał` | Ranking aktywności z ostatnich 3 miesięcy | Wyznaczona ranga |
| `!czas-alltime` | Ranking aktywności wszechczasów | Wyznaczona ranga |
| `!czas-afazja` | Kanał Afazja – Pt/Sb 20:00–06:00 (all time) | Wyznaczona ranga |
| `!czas-kto [@nick]` | Szczegółowe statystyki konkretnej osoby | Wyznaczona ranga |
| `!pomoc` | Lista wszystkich komend | Wyznaczona ranga |

Osoby bez wyznaczonej rangi (`STATS_ROLE_ID`) i bez uprawnień administratora mają wiadomość z komendą cicho usuwaną.

---

## ⏱️ Śledzenie aktywności głosowej

Bot nasłuchuje zdarzeń Discorda (`on_voice_state_update`) i automatycznie zlicza czas na **wszystkich** kanałach głosowych serwera — nie trzeba nigdzie wskazywać listy kanałów, nowo utworzone kanały są śledzone od razu.

Dwa wyjątki:

- **Kanał AFK** — całkowicie wykluczony ze śledzenia (ID zapisane na stałe w kodzie).
- **Osoby ogłuszone** (`deaf` lub `self_deaf`) — czas nie jest liczony dopóki dźwięk jest wyłączony; wraca automatycznie po odgłuszeniu się.

---

## 🎉 Specjalny kanał „Afazja"

Jeden wskazany kanał głosowy (`SPECIAL_CHANNEL_ID`) śledzony jest **dodatkowo i osobno**, tylko w oknie czasowym:

- **Piątek** 20:00 – 06:00 (sobota)
- **Sobota** 20:00 – 06:00 (niedziela)

Czas poza tym oknem trafia wyłącznie do statystyk ogólnych.

---

## 📢 Automatyczne ogłoszenia Afazja

W każdy **piątek i sobotę** bot wysyła trzy embedowane wiadomości na kanał `ANNOUNCE_CHANNEL_ID`:

| Godzina | Treść |
|---|---|
| **10:00** | Główne ogłoszenie (tytuł zależny od dnia: piątkowy / sobotni), z reakcją 🥚 |
| **15:00** | Pierwsze przypomnienie |
| **19:00** | Drugie przypomnienie |

Każda wiadomość oznacza rangi BROJLER / OPIERZONY / PISKLAK i może zawierać obrazek (`ANNOUNCE_IMAGE_URL`).

---

## 📨 Automatyczne raporty

- **Miesięczny** – 1. dzień każdego miesiąca o 10:00, na kanał `REPORT_CHANNEL_ID`
- **Kwartalny** – 1 stycznia / kwietnia / lipca / października o 10:00
  Zawiera dodatkowo listę członków którzy nigdy nie pojawili się na żadnym kanale głosowym.

---

## 🎖️ System rang aktywności

Bot sprawdza progi aktywności **co godzinę**. Czas liczony łącznie ze zwykłych kanałów i kanału Afazja.

| Próg | Akcja |
|---|---|
| 48h łącznie | Nadaj **OPIERZONY**, usuń **PISKLAK** |
| 96h łącznie | Nadaj **BROJLER**, usuń **OPIERZONY** |

Przy awansie bot wysyła ogłoszenie z gratulacjami na kanał `ROLE_ANNOUNCE_CHANNEL_ID`. Ranga PISKLAK musi być nadana ręcznie nowym członkom — bot ją tylko odbiera przy awansie, nigdy nie nadaje.

---

## 🌐 Dashboard webowy

Panel dostępny w przeglądarce, chroniony logowaniem przez Discord OAuth2. Komunikuje się z botem przez wewnętrzne REST API (patrz sekcja niżej).

| Zakładka | Zawartość |
|---|---|
| 📊 Rankingi | Tabele aktywności (7 dni / 30 dni / kwartał / all time / Afazja), filtr po randze, wyszukiwarka, eksport CSV |
| 📈 Wykresy | Dzienna aktywność (30 dni), aktywność miesięczna (12 miesięcy) i tygodniowa (8 tygodni) |
| 📨 Raporty | Historia automatycznie wysłanych raportów |
| 🎖️ Rangi | Historia nadanych rang z datami |
| 😴 Nieaktywni | Lista członków którzy nigdy nie byli na kanale głosowym |
| 🏆 Rekordy | Lider wszechczasów, najdłuższa sesja, król Afazji, rekordy dobowe/tygodniowe |

Rangi wyświetlane w dashboardzie pochodzą bezpośrednio z Discorda (nie tylko z przeliczonego czasu) — dzięki temu ręcznie nadane rangi też są poprawnie pokazywane. Dane o rangach są cache'owane po stronie bota na 60 sekund i odświeżane natychmiast po każdej automatycznej zmianie rangi.

---

## 🔌 HTTP API bota (wewnętrzne, dla dashboardu)

Wszystkie endpointy wymagają nagłówka `Authorization: Bearer <DASHBOARD_SECRET>`.

| Endpoint | Zwraca |
|---|---|
| `GET /api/health` | Status bota |
| `GET /api/online` | Osoby aktualnie na kanałach głosowych |
| `GET /api/stats/{period}` | Ranking dla okresu: `week` / `month` / `quarter` / `alltime` |
| `GET /api/special` | Ranking kanału Afazja (all time) |
| `GET /api/reports` | Historia raportów |
| `GET /api/inactive` | Członkowie bez żadnej aktywności głosowej |
| `GET /api/role-grants` | Historia nadanych rang |
| `GET /api/activity-chart` | Dzienna aktywność – ostatnie 30 dni |
| `GET /api/monthly-activity` | Aktywność miesięczna – ostatnie 12 miesięcy |
| `GET /api/weekly-activity` | Aktywność tygodniowa – ostatnie 8 tygodni |
| `GET /api/member-roles` | Aktualne rangi wszystkich członków (cache 60s) |
| `GET /api/records` | Rekordy serwera |
| `GET /api/server-stats` | Zbiorcze statystyki serwera |

---

## ⚙️ Zmienne środowiskowe (Railway)

| Zmienna | Opis |
|---|---|
| `DISCORD_TOKEN` | Token bota Discord |
| `DATABASE_URL` | Baza PostgreSQL (Railway uzupełnia automatycznie) |
| `SPECIAL_CHANNEL_ID` | ID kanału głosowego Afazja |
| `REPORT_CHANNEL_ID` | ID kanału tekstowego na automatyczne raporty |
| `ROLE_ANNOUNCE_CHANNEL_ID` | ID kanału tekstowego na ogłoszenia o nadaniu rang |
| `STATS_ROLE_ID` | ID rangi uprawnionej do używania komend statystyk |
| `ROLE_PISKLAK_ID` | ID rangi startowej (usuwana przy 48h) |
| `ROLE_OPIERZONY_ID` | ID rangi nadawanej po 48h |
| `ROLE_BROJLER_ID` | ID rangi nadawanej po 96h |
| `ANNOUNCE_CHANNEL_ID` | ID kanału tekstowego na ogłoszenia Afazja |
| `ANNOUNCE_IMAGE_URL` | Bezpośredni URL obrazka w ogłoszeniach |
| `DASHBOARD_SECRET` | Klucz łączący bota z dashboardem |
| `TIMEZONE` | Strefa czasowa (domyślnie `Europe/Warsaw`) |
| `COMMAND_PREFIX` | Prefix komend (domyślnie `!`) |

**Uwaga:** ID kanału AFK (`AFK_CHANNEL_ID`) i ID kanału głosowego Afazja wzmiankowanego w ogłoszeniach (`EVENT_VOICE_CHANNEL_ID`) są zapisane na stałe w `bot.py` — nie mają odpowiadających zmiennych środowiskowych.

---

## 🗄️ Schemat bazy danych

```
voice_sessions      – sesje na kanałach głosowych
report_log          – historia wysłanych raportów
role_grants          – historia nadanych rang
```

---

## 🚀 Stack technologiczny

- **Python 3.11+** z biblioteką `discord.py`
- **PostgreSQL** na Railway (`asyncpg`)
- **aiohttp** – wbudowany HTTP server dla dashboardu
- **FastAPI + uvicorn** – backend dashboardu (osobny serwis Railway)
- **Chart.js** – wykresy w dashboardzie
