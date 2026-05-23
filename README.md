# 🎙️ Discord Voice Tracker Bot

Bot do zliczania czasu spędzonego na kanałach głosowych Discorda.  
Działa 24/7 na Railway.com z bazą PostgreSQL.

---

## 📋 Funkcje

| Komenda | Opis |
|---|---|
| `!czas-tydzień` | Ranking aktywności z ostatnich 7 dni |
| `!czas-miesiąc` | Ranking aktywności z ostatnich 30 dni |
| `!czas-półrocze` | Ranking aktywności z ostatnich 6 miesięcy |
| `!czas-alltime` | Ranking wszechczasów |
| `!czas-specjalny` | Specjalny kanał – tylko Piątek/Sobota 20:00–02:00 |
| `!czas-kto [@nick]` | Statystyki konkretnej osoby (wszystkie okresy) |
| `!czas-online` | Kto teraz siedzi na kanale i jak długo |
| `!pomoc` | Lista komend |

### 🎉 Specjalny tryb kanału
Jeden wskazany kanał głosowy jest śledzony **osobno** – tylko w oknie czasowym:
- **Piątek** 20:00 – 23:59
- **Sobota** 00:00 – 02:00 i 20:00 – 23:59
- **Niedziela** 00:00 – 02:00

Czas poza tym oknem **nie jest** liczony do statystyk specjalnych (nadal do ogólnych).

---

## 🚀 Wdrożenie na Railway.com

### Krok 1 – Utwórz bota Discord

1. Wejdź na [discord.com/developers](https://discord.com/developers/applications)
2. **New Application** → nadaj nazwę
3. Zakładka **Bot** → **Add Bot** → skopiuj **Token**
4. Zakładka **Bot** → włącz:
   - `SERVER MEMBERS INTENT`
   - `MESSAGE CONTENT INTENT`
5. Zakładka **OAuth2 → URL Generator**:
   - Scope: `bot`
   - Bot Permissions: `View Channels`, `Send Messages`, `Read Message History`, `Connect`, `View Audit Log`
6. Skopiuj wygenerowany URL i zaproś bota na swój serwer

### Krok 2 – Utwórz projekt na Railway

1. Zaloguj się na [railway.com](https://railway.com)
2. **New Project → Deploy from GitHub repo** (lub „Empty Project")
3. Jeśli GitHub: wrzuć pliki bota do repozytorium i podłącz je do Railway
4. Jeśli ręcznie: użyj **Railway CLI**:
   ```bash
   npm install -g @railway/cli
   railway login
   railway init
   railway up
   ```

### Krok 3 – Dodaj PostgreSQL

1. W projekcie Railway kliknij **+ New** → **Database** → **Add PostgreSQL**
2. Po chwili baza jest gotowa
3. Kliknij bazę → zakładka **Connect** → skopiuj `DATABASE_URL`

### Krok 4 – Ustaw zmienne środowiskowe

W Railway → Twój serwis → zakładka **Variables** dodaj:

```
DISCORD_TOKEN       = <token z kroku 1>
DATABASE_URL        = <connection string z kroku 3>  ← Railway może to ustawić automatycznie
SPECIAL_CHANNEL_ID  = <ID kanału głosowego>
TIMEZONE            = Europe/Warsaw
COMMAND_PREFIX      = !
```

> **Jak zdobyć ID kanału?**  
> Discord → Ustawienia → Zaawansowane → włącz **Tryb Dewelopera**  
> Kliknij PPM na kanale głosowym → **Kopiuj ID**

### Krok 5 – Deploy

Railway wykryje `Procfile` i uruchomi `python bot.py` automatycznie.  
W zakładce **Logs** zobaczysz `✅ Zalogowano jako NazwaBota`.

---

## 🗄️ Baza danych – schemat

```sql
voice_sessions
├── id            BIGSERIAL PRIMARY KEY
├── user_id       BIGINT          -- Discord User ID
├── display_name  TEXT            -- Aktualny nick (aktualizowany)
├── channel_id    BIGINT          -- ID kanału głosowego
├── channel_name  TEXT            -- Nazwa kanału
├── joined_at     TIMESTAMPTZ     -- Kiedy dołączył
├── left_at       TIMESTAMPTZ     -- Kiedy wyszedł (NULL = trwa)
├── duration_s    INTEGER         -- Czas trwania w sekundach
└── is_special    BOOLEAN         -- Czy to specjalny kanał w oknie czasowym
```

---

## 💡 Propozycje dodatkowych funkcji (od bota)

1. **`!czas-kanał #kanał`** – ranking tylko dla jednego kanału głosowego
2. **`!czas-streak`** – ile dni z rzędu ktoś był aktywny na voice (streak)
3. **Automatyczny raport tygodniowy** – bot wysyła w poniedziałek rano top 5 tygodnia na wybrany kanał tekstowy
4. **Role za aktywność** – automatyczne przyznawanie/odbieranie ról Discorda po przekroczeniu progów (np. 10h/miesiąc = rola „Aktywny")
5. **`!czas-wykres`** – wykres aktywności danego użytkownika jako obraz (matplotlib → wysłany jako attachment)

Dodanie tych funkcji wymaga rozbudowy `bot.py` i `database.py` – daj znać jeśli chcesz którąś z nich.

---

## 🔧 Lokalne uruchomienie (opcjonalne)

```bash
pip install -r requirements.txt
cp .env.example .env
# edytuj .env
python bot.py
```

Wymagany Python 3.11+.
