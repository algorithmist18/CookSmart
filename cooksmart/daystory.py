"""The day as a story: which meal uses what, and how the fridge changes (presentation layer over the real plan).

Stock itself is reconciled once, at close of day (agent.close_day). Meals served earlier in the day only record a
story event, and the fridge view subtracts what those meals used so the shelves visibly empty through the day.
"""
from __future__ import annotations

from . import inventory as inv
from .recipes import ITEMS, RECIPES

MEALS = ("breakfast", "lunch", "dinner")
SHARE = {"lunch": 0.6, "dinner": 0.4}          # the non-breakfast menu is cooked for lunch, then again for dinner

ICON = {"breakfast": "🌅", "lunch": "☀️", "dinner": "🌙"}

STAGES = [  # key, clock, title
    ("review", "9:00 PM", "Night check"), ("plan", "9:10 PM", "Menu picked"), ("shop", "9:30 PM", "Groceries ordered"),
    ("delivery", "9:45 PM", "Groceries arrive"), ("brief", "6:30 AM", "Cook briefed"),
    ("breakfast", "8:00 AM", "Breakfast"), ("lunch", "1:00 PM", "Lunch"), ("dinner", "8:30 PM", "Dinner"),
    ("wrapup", "10:00 PM", "Wrap-up")]

# emoji + fridge zone; "full" is a full pack, used to draw how full each shelf item is
ITEM_VIEW: dict[str, tuple[str, str]] = {
    "tomato": ("🍅", "veg"), "onion": ("🧅", "pantry"), "potato": ("🥔", "pantry"), "spinach": ("🥬", "veg"),
    "paneer": ("🧀", "dairy"), "cauliflower": ("🥦", "veg"), "peas": ("🫛", "veg"), "dal": ("🫘", "pantry"),
    "rice": ("🍚", "pantry"), "atta": ("🌾", "pantry"), "curd": ("🥛", "dairy"), "cream": ("🍦", "dairy"),
    "rajma": ("🫘", "pantry"), "cucumber": ("🥒", "veg"), "milk": ("🥛", "dairy"), "egg": ("🥚", "dairy"),
    "chicken": ("🍗", "protein"), "bhindi": ("🥬", "veg"), "brinjal": ("🍆", "veg"), "cabbage": ("🥬", "veg"),
    "carrot": ("🥕", "veg"), "beans": ("🫛", "veg"), "capsicum": ("🫑", "veg"), "lauki": ("🥒", "veg"),
    "mushroom": ("🍄", "veg"), "moong": ("🫘", "pantry"), "masoor": ("🫘", "pantry"), "chana": ("🫘", "pantry"),
    "besan": ("🌾", "pantry"), "poha": ("🍚", "pantry"), "suji": ("🌾", "pantry"), "bread": ("🍞", "dairy"),
    "sabudana": ("⚪", "pantry"), "kuttu": ("🌾", "pantry"), "samak": ("🍚", "pantry"), "peanuts": ("🥜", "pantry"),
    "banana": ("🍌", "veg"), "apple": ("🍎", "veg"),
}


def view(item: str) -> dict:
    emo, zone = ITEM_VIEW.get(item, ("🥫", "pantry"))
    return {"emoji": emo, "zone": zone, "full": ITEMS.get(item, {}).get("pack", 1)}


def meals_of(plan: dict) -> dict[str, list[str]]:
    """The plan's own breakfast/lunch/dinner. Dishes it doesn't place go to lunch; old plans fall back to a guess."""
    m = plan.get("meals") or {}
    if not m:
        return split(plan["chosen"])
    out = {k: [r for r in m.get(k, []) if r in plan["chosen"]] for k in MEALS}
    out["lunch"] += [r for r in plan["chosen"] if not any(r in v for v in out.values())]
    return out


def split(chosen: list[str]) -> dict[str, list[str]]:
    bf = [r for r in chosen if RECIPES[r]["course"] == "breakfast"]
    rest = [r for r in chosen if r not in bf]
    return {"breakfast": bf, "lunch": rest, "dinner": list(rest)}


def meal_needs(plan: dict, scale: float, meal: str) -> dict[str, dict]:
    ids = meals_of(plan)[meal]
    share = 1.0 if (meal == "breakfast" or plan.get("meals")) else SHARE[meal]
    return {k: {"qty": round(v["qty"] * share, 1), "unit": v["unit"]} for k, v in inv.needs_for(ids, scale).items()}


def deltas_from(needs: dict[str, dict], sign: int = -1) -> list[dict]:
    return [{"item": k, "qty": sign * v["qty"], "unit": v["unit"]} for k, v in needs.items() if v["qty"]]


def consumed_so_far(plan: dict | None, scale: float) -> dict[str, float]:
    """Items already used by meals served today but not yet reconciled in stock."""
    if not plan or plan["state"] == "closed":
        return {}
    out: dict[str, float] = {}
    for meal in plan.get("served", []):
        for k, v in meal_needs(plan, scale, meal).items():
            out[k] = out.get(k, 0.0) + v["qty"]
    return out
