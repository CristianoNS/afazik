"""
dashboard/main.py – Panel webowy dla Discord Voice Tracker Bota.
Uruchamiany jako osobny serwis na Railway.
Logowanie przez Discord OAuth2.
"""
import os
import json
import secrets
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
import asyncpg

# ── Konfiguracja ──────────────────────────────────────────────────────────────
DATABASE_URL        = os.getenv("DATABASE_URL", "")
BOT_API_URL         = os.getenv("BOT_API_URL", "http://localhost:8080")
BOT_API_SECRET      = os.getenv("DASHBOARD_SECRET", "")
DISCORD_CLIENT_ID   = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_URL       = os.getenv("DASHBOARD_URL", "http://localhost:3000")
# ID użytkowników Discorda którzy mają dostęp do dashboardu (oddzielone przecinkami)
ALLOWED_USER_IDS    = set(os.getenv("DASHBOARD_ALLOWED_USERS", "").split(","))
SESSION_SECRET      = os.getenv("SESSION_SECRET", secrets.token_hex(32))
PORT                = int(os.getenv("DASHBOARD_PORT", "3000"))
TZ                  = ZoneInfo("Europe/Warsaw")

REDIRECT_URI = f"{DASHBOARD_URL}/auth/callback"

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    yield
    await pool.close()

app = FastAPI(title="Voice Tracker Dashboard", lifespan=lifespan)

# Prosta sesja in-memory (token → discord_user_id)
sessions: dict[str, str] = {}

# ── DB pool (zarządzany przez lifespan) ──────────────────────────────────────

pool: asyncpg.Pool | None = None

# ── Auth helpers ──────────────────────────────────────────────────────────────

def get_session_user(request: Request) -> str | None:
    token = request.cookies.get("session")
    if not token:
        return None
    return sessions.get(token)

def require_auth(request: Request) -> str:
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if ALLOWED_USER_IDS and user not in ALLOWED_USER_IDS and "0" not in ALLOWED_USER_IDS:
        raise HTTPException(status_code=403, detail="Brak dostępu.")
    return user

# ── OAuth2 ────────────────────────────────────────────────────────────────────

@app.get("/login")
async def login():
    scope = "identify"
    url   = (f"https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
             f"&redirect_uri={REDIRECT_URI}&response_type=code&scope={scope}")
    return RedirectResponse(url)

@app.get("/auth/callback")
async def auth_callback(code: str, request: Request):
    async with httpx.AsyncClient() as client:
        token_res = await client.post("https://discord.com/api/oauth2/token", data={
            "client_id":     DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
        })
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(400, "Błąd autoryzacji Discord.")

        user_res = await client.get("https://discord.com/api/users/@me",
                                    headers={"Authorization": f"Bearer {access_token}"})
        user_data = user_res.json()
        user_id   = user_data.get("id", "")

    if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS and "0" not in ALLOWED_USER_IDS:
        return HTMLResponse("<h2>Brak dostępu. Twoje konto Discord nie ma uprawnień.</h2>", status_code=403)

    session_token = secrets.token_hex(32)
    sessions[session_token] = user_id

    response = RedirectResponse("/")
    response.set_cookie("session", session_token, httponly=True, max_age=86400 * 7)
    return response

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        sessions.pop(token, None)
    response = RedirectResponse("/login")
    response.delete_cookie("session")
    return response

# ── Proxy do bota ─────────────────────────────────────────────────────────────

async def bot_get(endpoint: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{BOT_API_URL}{endpoint}",
                             headers={"Authorization": f"Bearer {BOT_API_SECRET}"})
        return r.json()

async def bot_post(endpoint: str, data: dict):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{BOT_API_URL}{endpoint}",
                              json=data,
                              headers={"Authorization": f"Bearer {BOT_API_SECRET}"})
        return r.json()

# ── API endpointy dashboardu ──────────────────────────────────────────────────

@app.get("/api/health")
async def api_health(request: Request):
    """Publiczny health-check – bez wymogu logowania, dla UptimeRobot i innych monitorów."""
    return await bot_get("/api/health")

@app.get("/api/stats/{period}")
async def api_stats(period: str, request: Request):
    require_auth(request)
    return await bot_get(f"/api/stats/{period}")

@app.get("/api/special")
async def api_special(request: Request):
    require_auth(request)
    return await bot_get("/api/special")

@app.get("/api/reports")
async def api_reports(request: Request):
    require_auth(request)
    return await bot_get("/api/reports")

@app.get("/api/inactive")
async def api_inactive(request: Request):
    require_auth(request)
    return await bot_get("/api/inactive")

@app.get("/api/role-grants")
async def api_role_grants(request: Request):
    require_auth(request)
    return await bot_get("/api/role-grants")

@app.get("/api/online")
async def api_online(request: Request):
    require_auth(request)
    return await bot_get("/api/online")

@app.get("/api/monthly-activity")
async def api_monthly_activity(request: Request):
    require_auth(request)
    return await bot_get("/api/monthly-activity")

@app.get("/api/weekly-activity")
async def api_weekly_activity(request: Request):
    require_auth(request)
    return await bot_get("/api/weekly-activity")

@app.get("/api/records")
async def api_records(request: Request):
    require_auth(request)
    return await bot_get("/api/records")

@app.get("/api/server-stats")
async def api_server_stats(request: Request):
    require_auth(request)
    return await bot_get("/api/server-stats")

@app.get("/api/stale-ranked")
async def api_stale_ranked(request: Request):
    require_auth(request)
    return await bot_get("/api/stale-ranked")

@app.get("/api/member-roles")
async def api_member_roles(request: Request):
    require_auth(request)
    return await bot_get("/api/member-roles")

@app.get("/api/activity-chart")
async def api_activity_chart(request: Request):
    require_auth(request)
    return await bot_get("/api/activity-chart")

# ── Główna strona – SPA ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/login")
    if ALLOWED_USER_IDS and user not in ALLOWED_USER_IDS and "0" not in ALLOWED_USER_IDS:
        return HTMLResponse("<h2>Brak dostępu.</h2>", status_code=403)

    with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
