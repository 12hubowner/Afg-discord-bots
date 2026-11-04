import os
import re
import time
import secrets
import aiosqlite

DB_PATH = os.environ.get("KEYHUB_DB", "keyhub.db")

_DISCORD_RE = re.compile(r"^\d{17,20}$")
_KEY_RE = re.compile(r"^[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}$")
_HWID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _conn():
    return aiosqlite.connect(DB_PATH)


async def init_db():
    async with _conn() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("PRAGMA foreign_keys=ON")
        with open("schema.sql", "r", encoding="utf-8") as f:
            await db.executescript(f.read())
        await db.commit()


def generate_key() -> str:
    hex_str = secrets.token_hex(8).upper()
    return f"{hex_str[:4]}-{hex_str[4:8]}-{hex_str[8:12]}-{hex_str[12:16]}"


def _valid_discord_id(discord_id) -> bool:
    return bool(_DISCORD_RE.match(str(discord_id)))


async def create_key(discord_id: int, key_days: int | None, note: str = "") -> str:
    if not _valid_discord_id(discord_id):
        raise ValueError("invalid discord_id")
    if key_days is not None and (not isinstance(key_days, int) or key_days <= 0):
        raise ValueError("invalid key_days")
    if not isinstance(note, str) or len(note) > 512:
        raise ValueError("invalid note")

    key = generate_key()
    async with _conn() as db:
        await db.execute(
            "INSERT INTO keys (key, discord_id, key_days, note) VALUES (?, ?, ?, ?)",
            (key, int(discord_id), key_days, note),
        )
        await db.commit()
    return key


async def get_key(key: str):
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return None
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM keys WHERE key = ?", (key,)) as cur:
            return await cur.fetchone()


async def get_user_key(discord_id: int):
    if not _valid_discord_id(discord_id):
        return None
    async with _conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM keys WHERE discord_id = ? ORDER BY rowid DESC LIMIT 1",
            (int(discord_id),),
        ) as cur:
            return await cur.fetchone()


async def bind_hwid(key: str, hwid: str) -> bool:
    """Atomic first-bind. True = we bound it; False = already bound (re-read and compare)."""
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return False
    if not isinstance(hwid, str) or not _HWID_RE.match(hwid):
        return False

    now = int(time.time())
    async with _conn() as db:
        cur = await db.execute(
            """
            UPDATE keys
               SET hwid = ?, activated_at = ?,
                   auth_expire = CASE
                       WHEN key_days IS NULL THEN NULL
                       ELSE ? + key_days * 86400
                   END
             WHERE key = ? AND hwid IS NULL
            """,
            (hwid, now, now, key),
        )
        await db.commit()
        return cur.rowcount == 1


# ---- per-key admin ops (change to WHERE discord_id = ? for per-user) ----

async def reset_hwid(key: str) -> bool:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return False
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE keys SET hwid = NULL, activated_at = NULL, auth_expire = NULL "
            "WHERE key = ?",
            (key,),
        )
        await db.commit()
        return cur.rowcount > 0


async def blacklist_key(key: str) -> bool:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return False
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE keys SET blacklisted = 1 WHERE key = ?", (key,)
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_key(key: str) -> bool:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return False
    async with _conn() as db:
        cur = await db.execute("DELETE FROM keys WHERE key = ?", (key,))
        await db.commit()
        return cur.rowcount > 0


async def unblacklist_key(key: str) -> bool:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return False
    async with _conn() as db:
        cur = await db.execute(
            "UPDATE keys SET blacklisted = 0 WHERE key = ?", (key,)
        )
        await db.commit()
        return cur.rowcount > 0


# ---- settings ----

async def set_setting(key: str, value: str):
    if not isinstance(key, str) or not isinstance(value, str):
        raise ValueError("settings key/value must be strings")
    async with _conn() as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


async def get_setting(key: str, default: str | None = None):
    async with _conn() as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default


async def get_all_stats():
    async with _conn() as db:
        async with db.execute(
            "SELECT "
            "  (SELECT COUNT(*) FROM keys), "
            "  (SELECT COUNT(*) FROM keys WHERE hwid IS NOT NULL), "
            "  (SELECT COUNT(*) FROM keys WHERE blacklisted = 1)"
        ) as cur:
            total, active, blacklisted = await cur.fetchone()
        return total, active, blacklisted
