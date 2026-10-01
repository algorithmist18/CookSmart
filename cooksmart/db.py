from __future__ import annotations

import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS households (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_phone TEXT,
    cook_phone TEXT,
    cook_language TEXT NOT NULL DEFAULT 'hi-IN',
    order_mode TEXT NOT NULL DEFAULT 'approve',      -- 'approve' | 'auto'
    auto_cap INTEGER NOT NULL DEFAULT 500,           -- INR, max a single auto order
    mandate_ceiling INTEGER NOT NULL DEFAULT 2000,   -- INR, payment mandate ceiling
    price_ceiling_factor REAL NOT NULL DEFAULT 1.5,  -- offer above fair price * factor = overpriced
    cook_arrival TEXT NOT NULL DEFAULT '08:00',
    pincode TEXT NOT NULL DEFAULT '560001',
    preferences TEXT NOT NULL DEFAULT '{}',
    cook_voice_enrolled INTEGER NOT NULL DEFAULT 0,
    family_size INTEGER NOT NULL DEFAULT 4,
    sim_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
    household_id TEXT NOT NULL,
    name TEXT NOT NULL,
    qty REAL NOT NULL,
    unit TEXT NOT NULL,
    expires_on TEXT,
    confidence TEXT NOT NULL DEFAULT 'confirmed',    -- 'confirmed' | 'uncertain'
    last_confirmed TEXT NOT NULL,
    PRIMARY KEY (household_id, name)
);
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    day TEXT NOT NULL,
    dish_id TEXT NOT NULL,
    dish TEXT NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    day TEXT NOT NULL,                               -- the day the food is cooked
    state TEXT NOT NULL DEFAULT 'review',
    proposals TEXT NOT NULL DEFAULT '[]',
    chosen TEXT NOT NULL DEFAULT '[]',
    reviewed INTEGER NOT NULL DEFAULT 0,
    rejections INTEGER NOT NULL DEFAULT 0,
    feedback TEXT NOT NULL DEFAULT '[]',
    gaps TEXT NOT NULL DEFAULT '[]',
    offer TEXT,
    order_id INTEGER,
    brief TEXT,
    pending TEXT,                                    -- cook read-back awaiting yes/no
    report TEXT NOT NULL DEFAULT '{}',               -- what the cook reported using (S8)
    notes TEXT NOT NULL DEFAULT '[]',
    excluded TEXT NOT NULL DEFAULT '[]',             -- main dish ids the owner already passed on
    flags TEXT NOT NULL DEFAULT '{}'                 -- per-day: guests, fasting, light, cook_off, scale
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    plan_id INTEGER NOT NULL,
    store TEXT NOT NULL,
    items TEXT NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,                            -- accepted | cancelled | delivered | payment_failed
    eta_minutes INTEGER,
    provider_ref TEXT,
    waybill TEXT,
    payment_ref TEXT,
    authorization TEXT NOT NULL,                     -- owner_tap | auto_policy
    otp TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    channel TEXT NOT NULL,                           -- 'owner' | 'cook'
    sender TEXT NOT NULL,                            -- 'agent' | 'user'
    text TEXT NOT NULL,
    payload TEXT,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    kind TEXT NOT NULL,                              -- constraint | avoid_dish
    note TEXT NOT NULL,
    day TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    key TEXT NOT NULL,                               -- hash of (voice, text): identical text is stored once
    mime TEXT NOT NULL,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    reference_id TEXT PRIMARY KEY,                   -- our clientReferenceId: household:plan:type:n
    household_id TEXT NOT NULL,
    plan_id INTEGER,
    call_type TEXT NOT NULL,                         -- brief | reconcile
    status TEXT NOT NULL,                            -- placed | processed | failed
    conversation_id TEXT,                            -- Gnani's id, known once the webhook arrives
    disposition TEXT,
    payload TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id TEXT NOT NULL,
    kind TEXT NOT NULL,                              -- prompt | doc | faqs
    name TEXT NOT NULL,                              -- 'cook_call' | '03_swaad_aur_pasand.md' | 'faqs'
    content TEXT,                                    -- NULL = "reset to default" marker
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_studio ON studio_docs (household_id, kind, name, id);
CREATE INDEX IF NOT EXISTS idx_msg ON messages (household_id, channel, id);
"""


# Columns added after the first release: applied to databases created by older versions.
MIGRATIONS = [
    ("households", "family_size", "INTEGER NOT NULL DEFAULT 4"),
    ("plans", "excluded", "TEXT NOT NULL DEFAULT '[]'"),
    ("plans", "flags", "TEXT NOT NULL DEFAULT '{}'"),
]


class DB:
    """Thin sqlite wrapper. Every domain query in repo.py/inventory.py is scoped by household_id."""

    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            for table, col, ddl in MIGRATIONS:
                cols = [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")]
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None
