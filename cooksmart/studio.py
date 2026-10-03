"""Agent Studio: the owner's edits to the cook-call agent's system prompt, knowledge base and FAQs.

Defaults are generated (gnani_kb.py) or shipped (gnani/prompt.j2). An edit is saved as a new version; "reset" is a
marker row, so nothing is ever lost and any earlier version can be restored. Everything is per household.

Checks run before saving. Errors block (a prompt that does not render would fail on a live call); the one
safety-critical rule, that today's allergy cautions stay in the prompt, blocks unless the owner explicitly forces it.
"""
from __future__ import annotations

import json
import re

import jinja2

from . import gnani_kb, gnani_prompt, repo
from .cookbrief import to_variables
from .db import DB

PROMPT = "cook_call"
MAX_PROMPT, MAX_DOC = 20_000, 30_000
CUSTOM_RE = re.compile(r"^custom_[a-z0-9_\-]{1,48}\.md$")
DIAGNOSIS_WORDS = ("diabet", "मधुमेह", "शुगर की बीमारी", "high bp", "high_bp", "ब्लड प्रेशर", "cholesterol", "कोलेस्ट्रॉल",
                   "thyroid", "थायराइड", "cancer", "कैंसर", "hiv")

VARIABLES = [
    ("call_type", "brief or reconcile"), ("cook_name", "how to address her"), ("people", "how many are eating today"),
    ("dishes_hi", "today's menu"), ("start_dishes_hi", "dishes she can start now"),
    ("wait_dishes_hi", "dishes waiting for ingredients"), ("ingredients_hi", "ingredients and amounts for the menu"),
    ("use_first_hi", "what must be used first, and why"), ("coming_hi", "missing items that are on the way"),
    ("missing_hi", "items not available today"), ("cautions_hi", "allergies and house rules for today"),
    ("taste_tips_hi", "tips for the best taste"), ("health_note_hi", "plain health note for the menu"),
    ("people_notes_hi", "per-person cooking instructions"), ("style_hi", "house style: spice, oil, salt, sugar"),
    ("owner_note_hi", "a message from the owner"), ("reconcile_items_hi", "items to check in the evening call"),
]


# ------------------------------------------------------------------ versions
def _latest(db: DB, hid: str, kind: str, name: str) -> dict | None:
    return db.one("SELECT id, content, created_at FROM studio_docs WHERE household_id=? AND kind=? AND name=? "
                  "ORDER BY id DESC LIMIT 1", (hid, kind, name))


def override(db: DB, hid: str, kind: str, name: str) -> str | None:
    row = _latest(db, hid, kind, name)
    return row["content"] if row else None


def save(db: DB, hid: str, kind: str, name: str, content: str | None) -> int:
    return db.execute("INSERT INTO studio_docs (household_id, kind, name, content, created_at) VALUES (?,?,?,?,?)",
                      (hid, kind, name, content, repo.now_iso())).lastrowid


def reset(db: DB, hid: str, kind: str, name: str) -> None:
    if _latest(db, hid, kind, name):
        save(db, hid, kind, name, None)


def history(db: DB, hid: str, kind: str, name: str, limit: int = 10) -> list[dict]:
    rows = db.query("SELECT id, content, created_at FROM studio_docs WHERE household_id=? AND kind=? AND name=? "
                    "AND content IS NOT NULL ORDER BY id DESC LIMIT ?", (hid, kind, name, limit))
    return [{"id": r["id"], "created_at": r["created_at"], "chars": len(r["content"])} for r in rows]


def restore(db: DB, hid: str, version_id: int) -> dict | None:
    row = db.one("SELECT kind, name, content FROM studio_docs WHERE household_id=? AND id=? AND content IS NOT NULL",
                 (hid, version_id))
    if row:
        save(db, hid, row["kind"], row["name"], row["content"])
    return row


# ------------------------------------------------------------------ current content = default unless edited
def current_prompt(db: DB, hid: str) -> tuple[str, bool]:
    o = override(db, hid, "prompt", PROMPT)
    return (o, True) if o is not None else (gnani_prompt.load_prompt(), False)


def current_docs(db: DB, hid: str, prefs: dict, family: int) -> list[dict]:
    out = []
    for name, default in gnani_kb.build_all_docs(prefs, family).items():
        o = override(db, hid, "doc", name)
        out.append({"name": name, "content": o if o is not None else default, "default": default,
                    "overridden": o is not None, "custom": False})
    names = {r["name"] for r in db.query("SELECT DISTINCT name FROM studio_docs WHERE household_id=? AND kind='doc'", (hid,))}
    for name in sorted(n for n in names if CUSTOM_RE.match(n)):
        o = override(db, hid, "doc", name)
        if o is not None:
            out.append({"name": name, "content": o, "default": "", "overridden": True, "custom": True})
    for d in out:
        d["title"] = (d["content"].splitlines() or [""])[0].lstrip("# ").strip() or d["name"]
        d["warnings"] = check_doc(d["name"], d["content"])["warnings"]
    return out


def current_faqs(db: DB, hid: str, prefs: dict) -> tuple[list[dict], list[dict], bool]:
    default = gnani_kb.build_all_faqs(prefs)
    o = override(db, hid, "faqs", "faqs")
    return (json.loads(o), default, True) if o is not None else (default, default, False)


# ------------------------------------------------------------------ checks
def check_prompt(content: str) -> dict:
    errors, warnings = [], []
    if not content.strip():
        return {"errors": ["The prompt is empty."], "warnings": [], "blocking_safety": False}
    if len(content) > MAX_PROMPT:
        errors.append(f"The prompt is {len(content)} characters; the limit here is {MAX_PROMPT}.")
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)
    try:
        env.parse(content)
    except jinja2.TemplateSyntaxError as e:
        errors.append(f"Template syntax error on line {e.lineno}: {e.message}")
    else:
        for kind in ("brief", "reconcile"):
            try:
                gnani_prompt.render(gnani_prompt.sample_variables(kind), content)
            except jinja2.UndefinedError as e:
                errors.append(f"Uses a variable CookSmart doesn't send: {e.message}. See the variable list.")
                break
            except jinja2.TemplateError as e:
                errors.append(f"Template error: {e}")
                break
    low = content.lower()
    blocking = "cautions_hi" not in content
    if blocking:
        warnings.append("Today's allergy cautions ({{ cautions_hi }}) are not in the prompt, so the agent would not say them on every call.")
    if "money" not in low and "price" not in low:
        warnings.append("Nothing tells the agent to stay away from money, prices and orders, which the cook must not hear about.")
    if "confirm" not in low and "सही है" not in content:
        warnings.append("Nothing tells the agent to read reports back and wait for a yes before treating them as confirmed.")
    if len(content) > 8000:
        warnings.append("A very long prompt makes calls slower and dearer.")
    return {"errors": errors, "warnings": warnings, "blocking_safety": blocking}


def check_doc(name: str, content: str) -> dict:
    errors, warnings = [], []
    if not content.strip():
        errors.append("The document is empty.")
    if len(content) > MAX_DOC:
        errors.append(f"The document is {len(content)} characters; the limit here is {MAX_DOC}.")
    low = content.lower()
    hits = sorted({w for w in DIAGNOSIS_WORDS if w in low})
    if hits:
        warnings.append("This looks like it names a health condition (" + ", ".join(hits) + "). Anything the cook can "
                        "retrieve should hold instructions only, like 'less salt', never the condition.")
    if "₹" in content:
        warnings.append("The cook must not hear about money; remove the amounts.")
    return {"errors": errors, "warnings": warnings}


def check_faqs(items) -> dict:
    errors = []
    if not isinstance(items, list):
        return {"errors": ["FAQs must be a list."], "warnings": []}
    if len(items) > 100:
        errors.append("Gnani allows at most 100 FAQs per agent.")
    for n, f in enumerate(items, 1):
        qs = f.get("questions") if isinstance(f, dict) else None
        if not isinstance(qs, list) or not qs or not all(isinstance(q, str) and q.strip() for q in qs):
            errors.append(f"FAQ {n}: needs at least one question.")
        elif len(qs) > 10:
            errors.append(f"FAQ {n}: at most 10 questions.")
        if not isinstance(f, dict) or not str(f.get("answer", "")).strip():
            errors.append(f"FAQ {n}: needs an answer.")
        elif len(f["answer"]) > 1000:
            errors.append(f"FAQ {n}: answer is longer than 1000 characters.")
    warnings = []
    blob = json.dumps(items, ensure_ascii=False).lower()
    if any(w in blob for w in DIAGNOSIS_WORDS):
        warnings.append("An FAQ mentions a health condition; use instructions only.")
    return {"errors": errors[:8], "warnings": warnings}


# ------------------------------------------------------------------ preview + export
def preview(db: DB, hid: str, content: str, call_type: str, live_variables: dict | None) -> dict:
    variables = live_variables or gnani_prompt.sample_variables(call_type)
    variables = {**variables, "call_type": call_type}
    return {"rendered": gnani_prompt.render(variables, content), "variables": variables,
            "using": "today's real plan" if live_variables else "sample data"}


def export_zip(db: DB, hid: str, prefs: dict, family: int) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("prompt.j2", current_prompt(db, hid)[0])
        for d in current_docs(db, hid, prefs, family):
            z.writestr(f"kb/{d['name']}", d["content"])
        z.writestr("kb/faqs.json", json.dumps(current_faqs(db, hid, prefs)[0], ensure_ascii=False, indent=2))
        z.writestr("UPLOAD.txt", "Gnani console > your agent:\n1. System prompt: paste prompt.j2\n"
                                 "2. Knowledge base: upload every file in kb/*.md\n3. FAQs: enter kb/faqs.json (max 100)\n")
    return buf.getvalue()


def live_variables(db: DB, hid: str, call_type: str) -> dict | None:
    """Today's real variables if there is a plan with a menu, so the preview shows exactly what the agent receives."""
    from . import cookbrief
    plan = repo.latest_plan(db, hid)
    if not plan or not plan["chosen"]:
        return None
    h = repo.get_household(db, hid)
    b = plan["brief"] or {"start": plan["chosen"], "wait": []}
    return to_variables(cookbrief.build(db, hid, h, plan, call_type=call_type, start=b["start"], wait=b["wait"],
                                        order_coming=plan["state"] == "ordered"))
