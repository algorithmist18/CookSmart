"""The daily brief for the cook: what she cannot know on her own.

She knows the recipes. She does not know what is in the kitchen, what must be used first and why, who is eating
and what they can't have, or how this family likes its food. This module assembles exactly that, in Hindi, from the
plan, the inventory ledger and the household profile.

Boundary: no money, prices, vendors, order details or delivery times ever appear here. Names of items that are
missing or on the way are fine; how they were bought is not.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import inventory as inv
from . import knowledge as kn
from . import profile as prof
from .recipes import ALLERGENS, ITEMS, RECIPES

MAX_FIELD = 700
WEEKDAYS_HI = {"monday": "सोमवार", "tuesday": "मंगलवार", "wednesday": "बुधवार", "thursday": "गुरुवार",
               "friday": "शुक्रवार", "saturday": "शनिवार", "sunday": "रविवार"}


@dataclass
class CookBriefData:
    call_type: str                      # brief | reconcile
    cook_name: str
    people: int
    dishes: list[str]                   # Hindi dish names
    start_dishes: list[str] = field(default_factory=list)
    wait_dishes: list[str] = field(default_factory=list)
    ingredients: list[str] = field(default_factory=list)       # "पालक 300 ग्राम"
    use_first: list[str] = field(default_factory=list)         # "पालक — आज ही इस्तेमाल करें. ..."
    coming: list[str] = field(default_factory=list)            # missing but on the way (names only)
    missing: list[str] = field(default_factory=list)           # missing and not coming
    cautions: list[str] = field(default_factory=list)          # allergies and house rules for today
    taste_tips: list[str] = field(default_factory=list)
    health_note: str = ""
    people_notes: str = ""
    style: str = ""
    owner_note: str = ""
    reconcile_items: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    """Values go into a Jinja2 prompt: strip template syntax and cap the length."""
    text = re.sub(r"(\{\{|\}\}|\{%|%\}|\{#|#\})", "", text or "").strip()
    return text[:MAX_FIELD]


def _customs_today(prefs: dict, cook_day: str) -> list[str]:
    weekday = dt.date.fromisoformat(cook_day).strftime("%A").lower()
    out = []
    for c in prefs.get("customs", []):
        if isinstance(c, str):
            out.append(c)
        elif not c.get("weekday") or c["weekday"].lower() == weekday:
            out.append(c.get("text", ""))
    return [c for c in out if c]


def cautions_for(prefs: dict, cook_day: str) -> list[str]:
    """Allergies are listed every time, whether or not today's menu contains the allergen: add-ons, tadka,
    garnish and shared spoons are where reactions happen."""
    out = []
    for g in sorted(prof.allergy_groups(prefs)):
        who = ", ".join(prof.who_is_allergic(prefs, g))
        out.append(f"{ALLERGENS[g]['hi']} बिलकुल नहीं डालनी ({who} को एलर्जी). उसी चम्मच/कड़छी का इस्तेमाल भी न करें, "
                   "तड़के, चटनी या सजावट में भी नहीं")
    return out + _customs_today(prefs, cook_day)


def build(db, hid: str, h: dict, plan: dict, *, call_type: str = "brief", start=None, wait=None,
          order_coming: bool = False, owner_note: str = "") -> CookBriefData:
    prefs = h["preferences"]
    scale = float(plan["flags"].get("scale", 1.0))
    chosen = plan["chosen"]
    stock = inv.available(db, hid, plan["day"], plan["day"])
    needs = inv.needs_for(chosen, scale)

    use_first, taste = [], []
    for item, n in needs.items():
        s = stock.get(item)
        care = kn.ITEM_CARE[item]
        if s and s["days_left"] is not None and s["days_left"] <= 1 and s["qty"] >= n["qty"]:
            line = f"{kn.hi_name(item)} — {kn.when_hi(s['days_left'])}"
            if care["use_up"]:
                line += f". {care['use_up']}"
            use_first.append(line)
        if s and s["days_left"] is not None and s["days_left"] <= 2 and care["taste"]:
            taste.append(f"{kn.hi_name(item)}: {care['taste']}")
    also = [kn.hi_name(i) for i, s in stock.items()
            if i not in needs and s["days_left"] is not None and s["days_left"] <= 1]
    if also:
        use_first.append("इनका भी ध्यान रखें, ये जल्दी ख़राब होंगे: " + ", ".join(also[:4]))

    gap_names = [kn.hi_name(g["name"]) for g in plan["gaps"]]
    members_text = prof.cook_safe_summary(prefs)

    ingredients = [f"{kn.hi_name(i)} {kn.qty_hi(n['qty'], n['unit'])}" for i, n in needs.items()]
    reconcile = [f"{kn.hi_name(i)} (लगभग {kn.qty_hi(n['qty'], n['unit'])} लगना था)" for i, n in needs.items()] \
        if call_type == "reconcile" else []

    return CookBriefData(
        call_type=call_type, cook_name=prefs.get("cook_name", "दीदी"),
        people=int(h["family_size"] + plan["flags"].get("guests", 0)),
        dishes=[RECIPES[r]["hi"] for r in chosen],
        start_dishes=[RECIPES[r]["hi"] for r in (start if start is not None else chosen)],
        wait_dishes=[RECIPES[r]["hi"] for r in (wait or [])],
        ingredients=ingredients, use_first=use_first,
        coming=gap_names if order_coming else [], missing=[] if order_coming else gap_names,
        cautions=cautions_for(prefs, plan["day"]),
        taste_tips=(taste + kn.dish_tips(chosen))[:4],
        health_note=kn.dish_health_note(chosen), people_notes=members_text,
        style="; ".join(prof.style_instructions(prefs)), owner_note=owner_note, reconcile_items=reconcile)


def to_variables(b: CookBriefData) -> dict[str, str]:
    """Flat strings for the Gnani prompt (Jinja2) and the trigger_call body."""
    j = lambda xs, sep="; ": sep.join(xs)           # noqa: E731
    raw = {
        "call_type": b.call_type, "cook_name": b.cook_name, "people": str(b.people),
        "dishes_hi": j(b.dishes, " और "), "start_dishes_hi": j(b.start_dishes, " और "),
        "wait_dishes_hi": j(b.wait_dishes, " और "), "ingredients_hi": j(b.ingredients, ", "),
        "use_first_hi": j(b.use_first), "coming_hi": j(b.coming, ", "), "missing_hi": j(b.missing, ", "),
        "cautions_hi": j(b.cautions), "taste_tips_hi": j(b.taste_tips), "health_note_hi": b.health_note,
        "people_notes_hi": b.people_notes.replace("\n", "; "), "style_hi": b.style, "owner_note_hi": b.owner_note,
        "reconcile_items_hi": j(b.reconcile_items),
    }
    return {k: _clean(v) for k, v in raw.items()}


def spoken_summary(b: CookBriefData) -> str:
    """A short Hindi text of the brief; also the fallback if the call can't be placed."""
    t = f"आज बनाना है: {' और '.join(b.dishes)}।"
    if b.wait_dishes and b.start_dishes:
        t += f" {' और '.join(b.wait_dishes)} का सामान अभी नहीं पहुँचा है, पहले {' और '.join(b.start_dishes)} शुरू करें।"
    if b.use_first:
        t += " पहले इस्तेमाल करें: " + b.use_first[0].split(".")[0] + "।"
    if b.cautions:
        t += " ध्यान रहे: " + b.cautions[0].split("(")[0].strip() + "।"
    return t
