# 🎙️ Discord Voice Tracker Bot – Afazja

Bot do zliczania czasu spędzonego na kanałach głosowych Discorda.  
Działa 24/7 na Railway.com z bazą PostgreSQL.

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
| `!czas-test` | Test wszystkich automatycznych procesów | Administrator |

---

## 🎉 Specjalny kanał „Afazja"

Jeden wskazany kanał głosowy śledzony osobno, tylko w oknie czasowym:

- **Piątek** 20:00 – 06:00 (sobota)
- **Sobota** 20:00 – 06:00 (niedziela)

Czas poza tym oknem trafia wyłącznie do statystyk ogólnych.

---

## 📨 Automatyczne raporty

- **Miesięczny** – 1. dzień każdego miesiąca o 10:00
- **Kwartalny** – 1 stycznia / kwietnia / lipca / października o 10:00  
  Zawiera dodatkowo listę członków którzy nigdy nie pojawili się na żadnym kanale głosowym.

---

## 🎖️ System rang aktywności

Czas liczony łącznie ze zwykłych kanałów i kanału Afazja.

| Próg | Akcja |
|---|---|
| 48h łącznie | Nadaj **OPIERZONY**, usuń **PISKLAK** |
| 96h łącznie | Nadaj **BROJLER**, usuń **OPIERZONY** i **PISKLAK** |

Przy awansie bot wysyła ogłoszenie z gratulacjami na wyznaczony kanał tekstowy.

---

## 🌐 Dashboard webowy

Panel dostępny w przeglądarce pod publicznym adresem Railway, chroniony logowaniem przez Discord OAuth2.

| Zakładka | Zawartość |
|---|---|
| 📊 Rankingi | Tabele aktywności (7 dni / 30 dni / kwartał / all time / Afazja) |
| 📈 Wykresy | Dzienna aktywność i liczba unikalnych użytkowników (ostatnie 30 dni) |
| 📨 Raporty | Historia automatycznie wysłanych raportów |
| 🎖️ Rangi | Historia nadanych rang z datami |
| 😴 Nieaktywni | Lista członków którzy nigdy nie byli na kanale głosowym |

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
| `DASHBOARD_SECRET` | Klucz łączący bota z dashboardem |
| `TIMEZONE` | Strefa czasowa (domyślnie `Europe/Warsaw`) |
| `COMMAND_PREFIX` | Prefix komend (domyślnie `!`) |

---

## 🗄️ Schemat bazy danych

```
voice_sessions      – sesje na kanałach głosowych
report_log          – historia wysłanych raportów
role_grants         – historia nadanych rang
```

---

## 🚀 Stack technologiczny

- **Python 3.11+** z biblioteką `discord.py`
- **PostgreSQL** na Railway
- **aiohttp** – wbudowany HTTP server dla dashboardu
- **FastAPI + uvicorn** – backend dashboardu
- **asyncpg** – asynchroniczny klient PostgreSQL
