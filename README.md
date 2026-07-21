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

## 🔔 Powiadomienia o progach i nieaktywności

Co godzinę, w oknie **8:00–22:00** czasu lokalnego (konfigurowalne, patrz niżej), bot sprawdza na kanale `NOTIFICATIONS_CHANNEL_ID`:

**1. Przekroczenie progu godzinowego** — gdy ktoś osiągnie 48h lub 96h łącznego czasu, bot wysyła jednorazowe powiadomienie:
> Angry Cake przekroczył/a próg 48h i spełnia wymóg uzyskania rangi OPIERZONY.

Powiadomienie **nie zostanie wysłane**, jeśli dana osoba **już ma** odpowiednią rangę na Discordzie (np. przypisaną wcześniej ręcznie) — bot sprawdza aktualny stan ról przed wysłaniem, żeby uniknąć bezsensownych alertów.

**2. Nieaktywność z rangą** — gdy osoba z rangą OPIERZONY/BROJLER nie pojawi się na żadnym kanale głosowym przez **30 dni**, bot wysyła powiadomienie o przejściu w stan nieaktywny:
> Angry Cake jest nieaktywny/a od 30 dni. Aktualnie ma rangę BROJLER.

Powiadomienie wysyłane jest tylko **raz przy przejściu** w stan nieaktywny (nie powtarza się co godzinę) — jeśli osoba wróci na kanał, a potem znów będzie nieaktywna przez 30 dni, dostaniesz nowe powiadomienie.

Poza oknem aktywnym (domyślnie 22:00–8:00) bot nic nie sprawdza — najbliższe uruchomienie w oknie aktywnym złapie te same zdarzenia, więc nic nie ginie, tylko jest przesunięte w czasie.

Bot **nic nie usuwa i nikogo nie powiadamia bezpośrednio** — to czysto informacyjne powiadomienia dla administratora; rangi nadal przypisujesz ręcznie.

---

## 👋 Powiadomienia o nowych członkach

Gdy ktoś dołączy do serwera, bot informuje na kanale `NOTIFICATIONS_CHANNEL_ID` kto dołączył i z jakiego zaproszenia skorzystał:
> NowyUser dołączył/a do serwera – zaproszony/a przez Angry Cake (kod: aB3xY9).

Bot porównuje liczbę użyć każdego linku zapraszającego przed i po dołączeniu, żeby ustalić który link został użyty. Obsługuje też zaproszenia jednorazowe (które znikają po użyciu) i link vanity URL serwera.

**Wymaga uprawnienia bota „Manage Server” (Zarządzaj serwerem)** — bez niego śledzenie zaproszeń jest wyłączone (bot zaloguje ostrzeżenie, ale nie przestanie działać).

---

## 🎖️ Rangi aktywności (nadawane ręcznie)

Bot **liczy czas** i pokazuje w dashboardzie ile brakuje do progu każdej rangi — ale **nie nadaje ich automatycznie**. Rangi przypisuje administrator ręcznie na Discordzie, na podstawie danych z dashboardu lub powiadomień opisanych wyżej.

| Ranga | Sugerowany próg |
|---|---|
| OPIERZONY | 48h łącznie |
| BROJLER | 96h łącznie |

Dashboard w zakładce **Rankingi → All time** pokazuje dokładny postęp każdej osoby (pasek + ile godzin brakuje). Aktualne rangi widoczne w dashboardzie są odczytywane bezpośrednio z Discorda — czyli to co ręcznie przypiszesz na serwerze, natychmiast odzwierciedla się w panelu (z zastrzeżeniem cache 60s, patrz niżej).

---

## 🌐 Dashboard webowy

Panel dostępny w przeglądarce, chroniony logowaniem przez Discord OAuth2. Komunikuje się z botem przez wewnętrzne REST API (patrz sekcja niżej).

| Zakładka | Zawartość |
|---|---|
| 📊 Rankingi | Tabele aktywności (7 dni / 30 dni / kwartał / all time / Afazja), filtr po randze, wyszukiwarka, eksport CSV, pasek postępu do następnej rangi (tylko w All time) |
| 📈 Wykresy | Dzienna aktywność (30 dni), aktywność miesięczna (12 miesięcy) i tygodniowa (8 tygodni) |
| 📨 Raporty | Historia automatycznie wysłanych raportów |
| 🎖️ Rangi | Historia nadanych rang z datami (tabela `role_grants` – obecnie niewypełniana automatycznie, log historyczny sprzed wyłączenia auto-nadawania) |
| 😴 Nieaktywni | Lista członków którzy nigdy nie byli na kanale głosowym |
| 🏆 Rekordy | Lider wszechczasów, najdłuższa sesja, król Afazji, rekordy dobowe/tygodniowe, plus tabela osób z rangą nieaktywnych 30+ dni |

---

## 🔌 HTTP API bota (wewnętrzne, dla dashboardu)

Wszystkie endpointy wymagają nagłówka `Authorization: Bearer <DASHBOARD_SECRET>` (porównywanego w sposób odporny na timing attack).

| Endpoint | Zwraca |
|---|---|
| `GET /api/health` | Rozszerzony status: uptime, liczba serwerów, aktywne sesje głosowe, status i opóźnienie bazy danych, opóźnienie Discorda |
| `GET /api/online` | Osoby aktualnie na kanałach głosowych |
| `GET /api/stats/{period}` | Ranking dla okresu: `week` / `month` / `quarter` / `alltime` |
| `GET /api/special` | Ranking kanału Afazja (all time) |
| `GET /api/reports` | Historia raportów |
| `GET /api/inactive` | Członkowie bez żadnej aktywności głosowej |
| `GET /api/role-grants` | Historia nadanych rang (log historyczny) |
| `GET /api/activity-chart` | Dzienna aktywność – ostatnie 30 dni |
| `GET /api/monthly-activity` | Aktywność miesięczna – ostatnie 12 miesięcy |
| `GET /api/weekly-activity` | Aktywność tygodniowa – ostatnie 8 tygodni |
| `GET /api/member-roles` | Aktualne rangi wszystkich członków, odczytane z Discorda (cache 60s) |
| `GET /api/records` | Rekordy serwera |
| `GET /api/server-stats` | Zbiorcze statystyki serwera |
| `GET /api/stale-ranked` | Osoby z rangą OPIERZONY/BROJLER nieaktywne 30+ dni |

`/api/health` jest też publicznie dostępny przez dashboard (`dashboard/main.py`, bez wymogu logowania) — można go podłączyć do zewnętrznego monitoringu jak UptimeRobot.

**Wydajność:** rangi wszystkich członków (`/api/member-roles`, `/api/stale-ranked` i wewnętrzne checkery powiadomień) korzystają ze wspólnego cache w pamięci ważnego 60 sekund, żeby ograniczyć liczbę zapytań `fetch_members` do Discord API przy częstym odświeżaniu dashboardu.

---

## ⚙️ Zmienne środowiskowe (Railway)

| Zmienna | Opis |
|---|---|
| `DISCORD_TOKEN` | Token bota Discord |
| `DATABASE_URL` | Baza PostgreSQL (Railway uzupełnia automatycznie) |
| `SPECIAL_CHANNEL_ID` | ID kanału głosowego Afazja |
| `REPORT_CHANNEL_ID` | ID kanału tekstowego na automatyczne raporty |
| `STATS_ROLE_ID` | ID rangi uprawnionej do używania komend statystyk |
| `ROLE_PISKLAK_ID` | ID rangi PISKLAK (do oznaczeń w ogłoszeniach i odczytu w dashboardzie) |
| `ROLE_OPIERZONY_ID` | ID rangi OPIERZONY (do oznaczeń, powiadomień i odczytu w dashboardzie) |
| `ROLE_BROJLER_ID` | ID rangi BROJLER (do oznaczeń, powiadomień i odczytu w dashboardzie) |
| `ANNOUNCE_CHANNEL_ID` | ID kanału tekstowego na ogłoszenia Afazja |
| `ANNOUNCE_IMAGE_URL` | Bezpośredni URL obrazka w ogłoszeniach |
| `DASHBOARD_SECRET` | Klucz łączący bota z dashboardem — **ustaw na stałą wartość w Railway**, w przeciwnym razie bot wygeneruje losowy klucz przy każdym restarcie i zerwie połączenie z dashboardem |
| `TIMEZONE` | Strefa czasowa (domyślnie `Europe/Warsaw`) |
| `COMMAND_PREFIX` | Prefix komend (domyślnie `!`) |
| `QUIET_HOURS_START` | Od której godziny wysyłać powiadomienia o progach/nieaktywności (domyślnie `8`) |
| `QUIET_HOURS_END` | Do której godziny (wyłącznie) wysyłać powiadomienia (domyślnie `22`) |

**Uwaga:** poniższe ID są zapisane na stałe w `bot.py` (nie mają zmiennych środowiskowych) — zmiana wymaga edycji kodu:
- `AFK_CHANNEL_ID` — kanał AFK wykluczony ze śledzenia
- `EVENT_VOICE_CHANNEL_ID` — kanał głosowy Afazja wzmiankowany w ogłoszeniach
- `NOTIFICATIONS_CHANNEL_ID` — kanał na powiadomienia o progach, nieaktywności i nowych członkach

---

## 🔐 Wymagane uprawnienia bota na Discordzie

Poza standardowymi (View Channels, Send Messages, Read Message History, Manage Roles) bot wymaga:
- **Manage Server** — do śledzenia zaproszeń (kto kogo zaprosił)
- Intencje uprzywilejowane: **Server Members Intent**, **Message Content Intent**

---

## 🗄️ Schemat bazy danych

```
voice_sessions      – sesje na kanałach głosowych
report_log          – historia wysłanych raportów
role_grants          – historyczny log nadanych rang (obecnie niewypełniany – auto-nadawanie wyłączone)
threshold_alerts     – kto już dostał powiadomienie o przekroczeniu progu 48h/96h
stale_rank_state     – aktualny stan "nieaktywny/aktywny" dla osób z rangą (do wykrywania przejść)
```

---

## 🚀 Stack technologiczny

- **Python 3.11+** z biblioteką `discord.py`
- **PostgreSQL** na Railway (`asyncpg`)
- **aiohttp** – wbudowany HTTP server dla dashboardu
- **FastAPI + uvicorn** – backend dashboardu (osobny serwis Railway)
- **Chart.js** – wykresy w dashboardzie
