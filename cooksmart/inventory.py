"""Inventory ledger (capability 2: cross_session_state_memory). Persistent across days, per household.

Rules enforced here:
* An item is "doubtful" if flagged uncertain, or perishable and not re-confirmed for STALE_DAYS.
  Doubtful stock is never planned around.
* Items past their use-by date for the cooking day are treated as spoiled (not available).
* A partial quantity is a gap (never "half an onion will do").
"""
from __future__ import annotations

import datetime as dt

from . import repo
from .db import DB
from .recipes import ITEMS, RECIPES, scale_qty

STALE_DAYS = 3


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def list_items(db: DB, hid: str) -> list[dict]:
    return db.query("SELECT * FROM inventory WHERE household_id=? ORDER BY name", (hid,))


def get(db: DB, hid: str, name: str) -> dict | None:
    return db.one("SELECT * FROM inventory WHERE household_id=? AND name=?", (hid, name))


def set_qty(db: DB, hid: str, name: str, qty: float, day: str, *, expires_on: str | None = None,
            confidence: str = "confirmed") -> None:
    unit = ITEMS[name]["unit"]
    cur = get(db, hid, name)
    if cur:
        exp = expires_on if expires_on is not None else cur["expires_on"]
        db.execute("UPDATE inventory SET qty=?, unit=?, expires_on=?, confidence=?, last_confirmed=? "
                   "WHERE household_id=? AND name=?", (qty, unit, exp, confidence, day, hid, name))
    else:
        db.execute("INSERT INTO inventory (household_id,name,qty,unit,expires_on,confidence,last_confirmed) "
                   "VALUES (?,?,?,?,?,?,?)", (hid, name, qty, unit, expires_on, confidence, day))


def add_stock(db: DB, hid: str, name: str, qty: float, day: str) -> None:
    """Delivered groceries: add to stock, expiry from the catalog shelf life (earliest wins)."""
    shelf = ITEMS[name]["shelf"]
    new_exp = (_d(day) + dt.timedelta(days=shelf)).isoformat() if shelf else None
    cur = get(db, hid, name)
    if cur and cur["qty"] > 0:
        exps = [e for e in (cur["expires_on"], new_exp) if e]
        set_qty(db, hid, name, cur["qty"] + qty, day, expires_on=min(exps) if exps else None)
    else:
        set_qty(db, hid, name, qty, day, expires_on=new_exp)


def mark_uncertain(db: DB, hid: str, name: str) -> None:
    db.execute("UPDATE inventory SET confidence='uncertain' WHERE household_id=? AND name=?", (hid, name))


def confirm_all(db: DB, hid: str, day: str) -> None:
    db.execute("UPDATE inventory SET confidence='confirmed', last_confirmed=? WHERE household_id=? AND qty>0",
               (day, hid))


def is_doubtful(item: dict, today: str) -> bool:
    if item["qty"] <= 0:
        return False
    if item["confidence"] == "uncertain":
        return True
    return bool(item["expires_on"]) and (_d(today) - _d(item["last_confirmed"])).days > STALE_DAYS


def is_spoiled(item: dict, cook_day: str) -> bool:
    return bool(item["expires_on"]) and _d(item["expires_on"]) < _d(cook_day)


def days_left(item: dict, cook_day: str) -> int | None:
    return (_d(item["expires_on"]) - _d(cook_day)).days if item["expires_on"] else None


def doubtful_items(db: DB, hid: str, today: str, cook_day: str) -> list[dict]:
    return [i for i in list_items(db, hid)
            if i["qty"] > 0 and not is_spoiled(i, cook_day) and is_doubtful(i, today)]


def spoiled_items(db: DB, hid: str, cook_day: str) -> list[dict]:
    return [i for i in list_items(db, hid) if i["qty"] > 0 and is_spoiled(i, cook_day)]


def available(db: DB, hid: str, today: str, cook_day: str) -> dict[str, dict]:
    """Confirmed, non-spoiled stock: the only stock the agent may plan around."""
    out = {}
    for i in list_items(db, hid):
        if i["qty"] > 0 and not is_spoiled(i, cook_day) and not is_doubtful(i, today):
            out[i["name"]] = {"qty": i["qty"], "unit": i["unit"], "days_left": days_left(i, cook_day)}
    return out


def needs_for(recipe_ids: list[str], scale: float = 1.0) -> dict[str, dict]:
    """Aggregate ingredient needs for a set of dishes, scaled for servings (recipes are for 4)."""
    needs: dict[str, dict] = {}
    for rid in recipe_ids:
        for item, (qty, unit) in RECIPES[rid]["needs"].items():
            slot = needs.setdefault(item, {"qty": 0.0, "unit": unit})
            slot["qty"] += scale_qty(qty, unit, scale)
    return needs


def gaps(needs: dict[str, dict], avail: dict[str, dict], raw: list[dict] | None = None) -> list[dict]:
    """Ingredients that are missing, short, or unconfirmed. Partial quantity counts as missing."""
    raw_by_name = {i["name"]: i for i in (raw or [])}
    out = []
    for item, need in needs.items():
        have = avail.get(item, {}).get("qty", 0.0)
        if have + 1e-9 >= need["qty"]:
            continue
        if item in avail:
            reason = "partial"
        elif item in raw_by_name and raw_by_name[item]["qty"] > 0:
            reason = "unconfirmed"
        else:
            reason = "absent"
        out.append({"name": item, "need": need["qty"], "have": have, "short": need["qty"] - have,
                    "unit": need["unit"], "reason": reason})
    return out


def apply_usage(db: DB, hid: str, needs: dict[str, dict], day: str, reported: set[str]) -> list[str]:
    """Deduct planned usage for items the cook did NOT report; those become 'uncertain'. Returns names."""
    touched = []
    for item, need in needs.items():
        if item in reported:
            continue
        cur = get(db, hid, item)
        if not cur:
            continue
        set_qty(db, hid, item, max(0.0, cur["qty"] - need["qty"]), day, confidence="uncertain")
        touched.append(item)
    return touched


DEFAULT_STOCK = [
    # (item, qty, days until use-by or None, days since last confirmed)
    ("tomato", 3, 2, 0), ("spinach", 300, 2, 0), ("paneer", 200, 4, 0),
    ("onion", 6, 15, 0), ("potato", 4, 14, 0), ("dal", 500, None, 0), ("rice", 1000, None, 0),
    ("atta", 800, None, 0), ("curd", 400, 4, 0), ("peas", 250, 5, 0),
    ("cauliflower", 300, 3, 0), ("cucumber", 3, 4, 0),
]


def seed(db: DB, hid: str, day: str, spec: list[tuple]) -> None:
    """Load a starting kitchen. Each row: (item, qty, days_to_use_by | None, days_since_confirmed)."""
    d = _d(day)
    for name, qty, exp_days, confirmed_ago in spec:
        expires = (d + dt.timedelta(days=exp_days)).isoformat() if exp_days is not None else None
        set_qty(db, hid, name, qty, (d - dt.timedelta(days=confirmed_ago)).isoformat(), expires_on=expires)
    repo.audit(db, hid, "seed_inventory", items=len(spec))


def seed_demo(db: DB, hid: str, day: str) -> None:
    """A realistic starting fridge: tomatoes and spinach are about to spoil; cream is missing."""
    seed(db, hid, day, DEFAULT_STOCK)
