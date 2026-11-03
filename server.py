import time
import os
import secrets
import base64
from aiohttp import web, ClientSession
from aiohttp_session import setup as setup_session, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import db

# ==========================================
# SECURE CONFIGURATION (Reads from Render Env)
# ==========================================
API_SECRET = "keyhub_9f3a8c7e2b1d4056_do_not_share"
PORT = int(os.environ.get("PORT", 8080))

# These must be set in Render -> Environment
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = "https://afg-discord-bots.onrender.com/callback"

# ==========================================

def load_script_body() -> str:
    try:
        with open("scripts/main.lua", "r") as f:
            return f.read()
    except FileNotFoundError:
        return '-- no script body configured'

def build_script(row, seconds_left: int) -> str:
    header = f"""-- LRM runtime vars
LRM_IsUserPremium = true
LRM_SecondsLeft = {seconds_left}
LRM_LinkedDiscordID = "{row['discord_id']}"
LRM_ScriptName = "keyhub"
-- end LRM
"""
    return header + "\n" + load_script_body()

async def handle_load(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    if data.get("secret") != API_SECRET:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=403)

    is_paused = await db.get_setting("system_paused", "0")
    if is_paused == "1":
        return web.json_response({"ok": False, "error": "paused"}, status=403)

    key = str(data.get("key", "")).strip()
    hwid = str(data.get("hwid", "")).strip()

    if not key or not hwid or hwid == "UNKNOWN":
        return web.json_response({"ok": False, "error": "missing_key_or_hwid"}, status=400)

    row = await db.get_key(key)
    if not row:
        return web.json_response({"ok": False, "error": "invalid_key"}, status=404)

    if row["blacklisted"]:
        return web.json_response({"ok": False, "error": "blacklisted"}, status=403)

    if not row["hwid"]:
        await db.bind_hwid(key, hwid)
        row = await db.get_key(key)
    elif row["hwid"] != hwid:
        return web.json_response({"ok": False, "error": "hwid_mismatch"}, status=403)

    if row["auth_expire"] and int(time.time()) >= row["auth_expire"]:
        return web.json_response({"ok": False, "error": "expired"}, status=403)

    seconds_left = 0
    if row["auth_expire"]:
        seconds_left = max(0, int(row["auth_expire"]) - int(time.time()))

    return web.json_response({
        "ok": True,
        "script": build_script(row, seconds_left),
        "seconds_left": seconds_left,
    })

async def handle_loader(request: web.Request) -> web.Response:
    if request.headers.get("X-Keyhub-Secret") != API_SECRET:
        return web.Response(text="403 Forbidden: Unauthorized", status=403)
    try:
        with open("loader.lua", "r") as f:
            return web.Response(text=f.read(), content_type="text/plain")
    except FileNotFoundError:
        return web.Response(text="-- loader missing.", status=404)

# ==========================================
# DISCORD OAUTH2 ROUTES
# ==========================================

async def handle_login(request):
    if not DISCORD_CLIENT_ID:
        return web.Response(text="Server configuration error: Missing DISCORD_CLIENT_ID in Render environment.", status=500)
        
    url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={DISCORD_REDIRECT_URI}"
        f"&response_type=code&scope=identify"
    )
    raise web.HTTPFound(url)

async def handle_callback(request):
    code = request.query.get("code")
    if not code:
        return web.Response(text="No code provided", status=400)

    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    async with ClientSession() as session:
        async with session.post("https://discord.com/api/oauth2/token", data=data, headers=headers) as resp:
            if resp.status != 200:
                return web.Response(text="Failed to get token. Check your Discord Client Secret in Render Environment Variables.", status=400)
            token_data = await resp.json()

        headers = {"Authorization": f"Bearer {token_data['access_token']}"}
        async with session.get("https://discord.com/api/users/@me", headers=headers) as resp:
            user_data = await resp.json()

    session = await get_session(request)
    session["user_id"] = user_data["id"]
    session["username"] = user_data["username"]
    session["avatar"] = user_data.get("avatar", "")

    raise web.HTTPFound("/")

async def handle_logout(request):
    session = await get_session(request)
    session.invalidate()
    raise web.HTTPFound("/")

# ==========================================
# DASHBOARD API
# ==========================================

async def api_me(request):
    session = await get_session(request)
    if "user_id" not in session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    user_id = int(session["user_id"])
    row = await db.get_user_key(user_id)

    if not row:
        return web.json_response({
            "ok": True,
            "user": session["username"],
            "has_key": False
        })

    seconds_left = 0
    if row["auth_expire"]:
        seconds_left = max(0, int(row["auth_expire"]) - int(time.time()))

    return web.json_response({
        "ok": True,
        "user": session["username"],
        "has_key": True,
        "key": row["key"],
        "hwid": row["hwid"] or "Not Bound",
        "expires": seconds_left,
        "blacklisted": bool(row["blacklisted"])
    })

# ==========================================
# WEBSITE ROUTES
# ==========================================

async def handle_index(request):
    return web.FileResponse('./public/index.html')

async def handle_css(request):
    return web.FileResponse('./public/style.css')

async def start_server():
    await db.init_db()
    app = web.Application()
    
    # Secure random key for session cookies
    secret_key = base64.urlsafe_b64decode(base64.b64encode(secrets.token_bytes(32)))
    setup_session(app, EncryptedCookieStorage(secret_key))

    # API
    app.router.add_post("/load", handle_load)
    app.router.add_get("/loader", handle_loader)
    app.router.add_get("/api/me", api_me)

    # Auth
    app.router.add_get("/login", handle_login)
    app.router.add_get("/callback", handle_callback)
    app.router.add_get("/logout", handle_logout)

    # Website
    app.router.add_get("/", handle_index)
    app.router.add_get("/style.css", handle_css)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[server] listening on :{PORT}")
    return runner
