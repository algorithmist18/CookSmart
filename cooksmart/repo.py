"""Persistence helpers. Everything is scoped by household_id: no query crosses households."""
from __future__ import annotations

import datetime as dt
import json

from .db import DB

PLAN_JSON = ("proposals", "chosen", "feedback", "gaps", "offer", "brief", "pending", "report", "notes", "excluded", "flags")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------- households ----------
def create_household(db: DB, hid: str, name: str, sim_date: str, **fields) -> dict:
    prefs = json.dumps(fields.pop("preferences", {}))
    cols = ["id", "name", "sim_date", "preferences", *fields]
    vals = [hid, name, sim_date, prefs, *fields.values()]
    db.execute(f"INSERT INTO households ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(vals))
    return get_household(db, hid)


def get_household(db: DB, hid: str) -> dict | None:
    h = db.one("SELECT * FROM households WHERE id=?", (hid,))
    if h:
        h["preferences"] = json.loads(h["preferences"] or "{}")
    return h


def find_household_by_phone(db: DB, phone: str) -> tuple[dict, str] | None:
    row = db.one("SELECT id FROM households WHERE owner_phone=?", (phone,))
    if row:
        return get_household(db, row["id"]), "owner"
    row = db.one("SELECT id FROM households WHERE cook_phone=?", (phone,))
    if row:
        return get_household(db, row["id"]), "cook"
    return None


def wipe_household_data(db: DB, hid: str) -> None:
    """Scenario reset: delete everything the household has accumulated (keeps the household row)."""
    for table in ("inventory", "meals", "plans", "orders", "messages", "audit", "memory"):
        db.execute(f"DELETE FROM {table} WHERE household_id=?", (hid,))


def update_household(db: DB, hid: str, **fields) -> None:
    if "preferences" in fields:
        fields["preferences"] = json.dumps(fields["preferences"])
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE households SET {sets} WHERE id=?", (*fields.values(), hid))


# ---------- plans ----------
def _decode_plan(row: dict | None) -> dict | None:
    if not row:
        return None
    for f in PLAN_JSON:
        row[f] = json.loads(row[f]) if row[f] else None
    for f in ("proposals", "chosen", "feedback", "gaps", "notes", "excluded", "flags"):
        row[f] = row[f] or []
    row["report"] = row["report"] or {}
    row["flags"] = row["flags"] or {}
    row["reviewed"] = bool(row["reviewed"])
    return row


def new_plan(db: DB, hid: str, day: str) -> dict:
    cur = db.execute("INSERT INTO plans (household_id, day) VALUES (?, ?)", (hid, day))
    return get_plan(db, hid, cur.lastrowid)


def get_plan(db: DB, hid: str, plan_id: int) -> dict | None:
    return _decode_plan(db.one("SELECT * FROM plans WHERE household_id=? AND id=?", (hid, plan_id)))


def latest_plan(db: DB, hid: str) -> dict | None:
    return _decode_plan(db.one("SELECT * FROM plans WHERE household_id=? ORDER BY id DESC LIMIT 1", (hid,)))


def update_plan(db: DB, hid: str, plan_id: int, **fields) -> dict:
    for k, v in list(fields.items()):
        if k in PLAN_JSON:
            fields[k] = json.dumps(v) if v is not None else None
        elif k == "reviewed":
            fields[k] = int(v)
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE plans SET {sets} WHERE household_id=? AND id=?", (*fields.values(), hid, plan_id))
    return get_plan(db, hid, plan_id)


# ---------- orders ----------
def _decode_order(row: dict | None) -> dict | None:
    if row:
        row["items"] = json.loads(row["items"])
    return row


def create_order(db: DB, hid: str, plan_id: int, **f) -> dict:
    f["items"] = json.dumps(f["items"])
    cols = ["household_id", "plan_id", "created_at", *f]
    vals = [hid, plan_id, now_iso(), *f.values()]
    cur = db.execute(f"INSERT INTO orders ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(vals))
    return get_order(db, hid, cur.lastrowid)


def get_order(db: DB, hid: str, order_id: int) -> dict | None:
    return _decode_order(db.one("SELECT * FROM orders WHERE household_id=? AND id=?", (hid, order_id)))


def list_orders(db: DB, hid: str) -> list[dict]:
    return [_decode_order(r) for r in db.query("SELECT * FROM orders WHERE household_id=? ORDER BY id", (hid,))]


def update_order(db: DB, hid: str, order_id: int, **fields) -> dict:
    sets = ", ".join(f"{k}=?" for k in fields)
    db.execute(f"UPDATE orders SET {sets} WHERE household_id=? AND id=?", (*fields.values(), hid, order_id))
    return get_order(db, hid, order_id)


# ---------- messages / audit / memory / meals ----------
def add_message(db: DB, hid: str, channel: str, sender: str, text: str, payload: dict | None = None) -> int:
    cur = db.execute(
        "INSERT INTO messages (household_id, channel, sender, text, payload, ts) VALUES (?,?,?,?,?,?)",
        (hid, channel, sender, text, json.dumps(payload) if payload else None, now_iso()))
    return cur.lastrowid


def list_messages(db: DB, hid: str, channel: str, after: int = 0) -> list[dict]:
    rows = db.query(
        "SELECT id, sender, text, payload, ts FROM messages WHERE household_id=? AND channel=? AND id>? ORDER BY id",
        (hid, channel, after))
    for r in rows:
        r["payload"] = json.loads(r["payload"]) if r["payload"] else None
    return rows


def audit(db: DB, hid: str, event: str, **detail) -> None:
    db.execute("INSERT INTO audit (household_id, ts, event, detail) VALUES (?,?,?,?)",
               (hid, now_iso(), event, json.dumps(detail, default=str)))


def list_audit(db: DB, hid: str, limit: int = 60) -> list[dict]:
    rows = db.query("SELECT ts, event, detail FROM audit WHERE household_id=? ORDER BY id DESC LIMIT ?",
                    (hid, limit))
    for r in rows:
        r["detail"] = json.loads(r["detail"])
    return rows


def add_memory(db: DB, hid: str, kind: str, note: str, day: str) -> None:
    db.execute("INSERT INTO memory (household_id, kind, note, day) VALUES (?,?,?,?)", (hid, kind, note, day))


def list_memory(db: DB, hid: str) -> list[dict]:
    return db.query("SELECT kind, note, day FROM memory WHERE household_id=? ORDER BY id", (hid,))


def add_meal(db: DB, hid: str, day: str, dish_id: str, dish: str, reviewed: bool) -> None:
    db.execute("INSERT INTO meals (household_id, day, dish_id, dish, reviewed) VALUES (?,?,?,?,?)",
               (hid, day, dish_id, dish, int(reviewed)))


def recent_meals(db: DB, hid: str, since_day: str) -> list[dict]:
    return db.query("SELECT day, dish_id, dish FROM meals WHERE household_id=? AND day>=? ORDER BY day",
                    (hid, since_day))


# ---------- media (synthesised voice notes) ----------
def add_media(db: DB, hid: str, key: str, mime: str, data: bytes) -> int:
    """Store a voice note; the same text is only ever synthesised (and billed) once per household."""
    row = db.one("SELECT id FROM media WHERE household_id=? AND key=?", (hid, key))
    if row:
        return row["id"]
    return db.execute("INSERT INTO media (household_id, key, mime, data) VALUES (?,?,?,?)",
                      (hid, key, mime, data)).lastrowid


def get_media(db: DB, hid: str, media_id: int) -> dict | None:
    return db.one("SELECT mime, data FROM media WHERE household_id=? AND id=?", (hid, media_id))
