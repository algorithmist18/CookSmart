"""Menu planning (S2). Claude proposes; deterministic code validates and computes gaps.

A "menu" is a small meal: a main plus companions (e.g. Palak Paneer + Roti, or Dal Tadka + Aloo Gobi + Rice).
Claude may only choose dishes from the recipe book (by id), so ingredient lists and quantities are never
hallucinated. A heuristic planner is the fallback and the offline mode.
"""
from __future__ import annotations

import datetime as dt
import dataclasses
from dataclasses import dataclass, field

from . import inventory as inv
from .nlu import find_items, norm, tokens
from .profile import allergy_items
from .recipes import DAIRY, ITEMS, JAIN_BANNED, RECIPES, fmt_qty

LIGHT_WORDS = {"light", "lighter", "halka", "halki", "healthy", "healthier", "diet"}


@dataclass
class PlanContext:
    cook_day: str
    stock: dict[str, dict]                      # confirmed, non-spoiled: name -> {qty, unit, days_left}
    recent_meals: list[dict] = field(default_factory=list)   # {day, dish_id, dish}
    preferences: dict = field(default_factory=dict)          # diet, lactose_free, likes, dislikes
    flags: dict = field(default_factory=dict)                # per-day: guests, fasting, light, cook_off, scale
    constraints: list[str] = field(default_factory=list)     # stove_broken | cooker_broken | time_short
    memory: list[dict] = field(default_factory=list)         # long-term notes
    feedback: list[str] = field(default_factory=list)        # owner's "something else" input
    exclude_ids: set[str] = field(default_factory=set)       # mains the owner already passed on
    today: str | None = None                                 # when the plan is made (default: the day before cook_day)

    @property
    def scale(self) -> float:
        return float(self.flags.get("scale", 1.0))

    @property
    def light(self) -> bool:
        return bool(self.flags.get("light")) or any(LIGHT_WORDS & set(tokens(f)) for f in self.feedback)


@dataclass
class Proposal:
    recipe_ids: list[str]
    name: str
    reason: str
    feasible: bool
    gaps: list[dict]
    repeat_days_ago: int | None = None
    stock_meals: dict = field(default_factory=dict)   # the same day using only stock on hand (used when a dish must be switched)
    extra_buy: list = field(default_factory=list)     # items breakfast/dinner need beyond lunch's gaps
    label: str = ""                              # why this option is worth picking ("Saves the most food")
    meals: dict = field(default_factory=dict)    # {"breakfast": [...], "lunch": [...], "dinner": [...]}; recipe_ids is their union

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Proposals:
    items: list[Proposal]
    tradeoffs: list[str]
    source: str


# ---------------------------------------------------------------- rules
def _excluded_items(ctx: PlanContext) -> set[str]:
    out = {norm(i) for i in ctx.preferences.get("dislikes", [])}
    weekday = dt.date.fromisoformat(ctx.cook_day).strftime("%A").lower()
    for c in ctx.preferences.get("customs", []):          # e.g. "no onion or garlic on Tuesdays"
        if isinstance(c, dict) and c.get("weekday", "").lower() == weekday:
            out |= set(c.get("avoid", []))
    for fb in ctx.feedback:
        toks = tokens(fb)
        if {"no", "not", "nahi", "without", "avoid", "नहीं"} & set(toks):
            out |= set(find_items(toks))
    return out


def allowed(rid: str, ctx: PlanContext) -> bool:
    """Hard filters: diet, fasting, allergies, broken appliances, time, cook off."""
    r = RECIPES[rid]
    needs = set(r["needs"])
    if needs & allergy_items(ctx.preferences):         # someone here reacts to it: never, whatever else is true
        return False
    diet = ctx.preferences.get("diet", "vegetarian")
    if r["diet"] == "nonveg" and diet != "nonveg":
        return False
    if r["diet"] == "egg" and diet not in ("nonveg", "eggetarian"):
        return False
    if diet == "jain" and needs & JAIN_BANNED:
        return False
    if ctx.flags.get("fasting") and "vrat" not in r["tags"]:
        return False
    if ctx.preferences.get("lactose_free") and needs & DAIRY:
        return False
    if ctx.flags.get("cook_off") and r["tools"]:
        return False
    if "stove_broken" in ctx.constraints and r["stove"]:
        return False
    if "cooker_broken" in ctx.constraints and "cooker" in r["tools"]:
        return False
    if "time_short" in ctx.constraints and r["prep"] > 30:
        return False
    if ctx.light and "heavy" in r["tags"]:
        return False
    return not (_excluded_items(ctx) & needs)


def _urgency_weight(days_left: int | None) -> float:
    if days_left is None:
        return 0
    return 4 if days_left <= 1 else 3 if days_left <= 2 else 1.5 if days_left <= 4 else 0


def _repeat_days(rid: str, ctx: PlanContext) -> int | None:
    cook = dt.date.fromisoformat(ctx.cook_day)
    best = None
    for m in ctx.recent_meals:
        if m["dish_id"] == rid:
            d = (cook - dt.date.fromisoformat(m["day"])).days
            best = d if best is None else min(best, d)
    return best


def _needs(ids: list[str], ctx: PlanContext) -> dict[str, dict]:
    return inv.needs_for(ids, ctx.scale)


def use_within(ctx: PlanContext, days_left: int) -> str:
    """'within 2 days (by Sat)': how long the owner has to eat it, counted from when the plan is made."""
    cook = dt.date.fromisoformat(ctx.cook_day)
    today = dt.date.fromisoformat(ctx.today) if ctx.today else cook - dt.timedelta(days=1)
    by = cook + dt.timedelta(days=days_left)
    n = max(0, (by - today).days)
    return f"{'today' if n == 0 else 'within ' + str(n) + (' day' if n == 1 else ' days')}, by {by.strftime('%a')}"


def _use_by(ctx: PlanContext, item: str) -> str:
    return use_within(ctx, ctx.stock[item]["days_left"])


def menu_name(ids: list[str]) -> str:
    return " + ".join(RECIPES[i]["name"] for i in ids)


def enrich(ids: list[str], ctx: PlanContext, reason: str | None = None) -> Proposal:
    needs = _needs(ids, ctx)
    gaps = inv.gaps(needs, ctx.stock)
    urgent = [i for i in needs if i in ctx.stock and ctx.stock[i]["days_left"] is not None
              and ctx.stock[i]["days_left"] <= 2 and ctx.stock[i]["qty"] >= needs[i]["qty"]]
    if not reason:
        if urgent:
            by_window: dict[str, list[str]] = {}
            for i in urgent:
                by_window.setdefault(_use_by(ctx, i), []).append(i)
            reason = "Uses up " + "; ".join(f"{', '.join(v)} ({w})" for w, v in by_window.items()) + "."
        else:
            reason = "Uses stock on hand."
        if ctx.scale != 1.0:
            reason += f" For {ctx.scale * 4:g} people."
    return Proposal(list(ids), menu_name(ids), reason, not gaps, gaps, _repeat_days(ids[0], ctx))


# ---------------------------------------------------------------- the day: breakfast, lunch, dinner
MEAL_ORDER = ("lunch", "dinner", "breakfast")      # recipe_ids is the union in this order, so recipe_ids[0] is lunch's main


def _take(left: dict, ids: list[str], ctx: PlanContext) -> None:
    for item, n in _needs(ids, ctx).items():
        if item in left:
            left[item]["qty"] = max(0.0, left[item]["qty"] - n["qty"])


def _fits(ids: list[str], ctx: PlanContext, left: dict, max_gaps: int = 0) -> bool:
    return bool(ids) and len(inv.gaps(_needs(ids, ctx), left)) <= max_gaps and all(allowed(i, ctx) for i in ids)


def _n_gaps(ids: list[str], ctx: PlanContext, left: dict) -> int:
    return len(inv.gaps(_needs(ids, ctx), left))


def _pick_breakfast(ctx: PlanContext, used: set[str], left: dict, max_gaps: int = 0) -> list[str]:
    best = None
    for rid, r in RECIPES.items():
        if r["course"] != "breakfast" or rid in used or rid in ctx.exclude_ids or not _fits([rid], ctx, left, max_gaps):
            continue
        rep = _repeat_days(rid, ctx)
        key = (_n_gaps([rid], ctx, left), -_urgency_of([rid], ctx), 1 if rep is not None and rep <= 3 else 0, r["prep"], rid)
        if best is None or key < best[0]:
            best = (key, rid)
    return [best[1]] if best else []


COMMON = {"onion", "tomato", "atta", "rice", "potato"}


def _dinner_candidates(ctx: PlanContext, used: set[str], left: dict, lunch: list[str], max_gaps: int = 0) -> list[tuple]:
    """Complete, lighter meals that differ from lunch (not the same kind of dish or ingredients), best first."""
    lunch_main = lunch[0]
    lunch_items = set(_needs(lunch, ctx)) - COMMON
    no_carb_needed = _no_heat(ctx) or bool(ctx.flags.get("fasting"))
    ctx2 = dataclasses.replace(ctx, stock=left, exclude_ids=set(ctx.exclude_ids) | used)
    cands = []
    for rid, r in RECIPES.items():
        if r["course"] not in _mainable(ctx) - {"breakfast"} or rid in used or rid == lunch_main or not allowed(rid, ctx2):
            continue
        ids = _build_menu(rid, ctx2, max_gaps)
        if not ids or any(i in used for i in ids) or not _fits(ids, ctx2, left, max_gaps):
            continue
        rep = _repeat_days(rid, ctx)
        complete = no_carb_needed or any(RECIPES[i]["course"] in ("carb", "one_pot") for i in ids)
        heavy = any("heavy" in RECIPES[i]["tags"] for i in ids)
        overlap = len((set(_needs(ids, ctx)) - COMMON) & lunch_items)
        key = (_n_gaps(ids, ctx2, left), 0 if complete else 1, 1 if heavy else 0, overlap, -_urgency_of(ids, ctx2), 1 if r["course"] == RECIPES[lunch_main]["course"] else 0,
               1 if rep is not None and rep <= 3 else 0, 0 if "light" in r["tags"] else 1, -len(ids), rid)
        cands.append((key, ids))
    return sorted(cands, key=lambda c: c[0])


def _pick_dinner(ctx: PlanContext, used: set[str], left: dict, lunch: list[str], max_gaps: int = 0) -> list[str]:
    cands = _dinner_candidates(ctx, used, left, lunch, max_gaps)
    return cands[0][1] if cands else []


def plan_day(lunch: list[str], ctx: PlanContext, breakfast: list[str] | None = None, dinner: list[str] | None = None,
             force_breakfast: bool = False, force_dinner: bool = False, avoid: set[str] = frozenset(),
             allow_buy: bool = False) -> dict:
    """Breakfast, lunch and dinner planned separately, each from what is left after the meals before it.
    A suggestion (e.g. from Claude) is used only if it is allowed and makeable from the remaining stock;
    otherwise the heuristic picks. A meal with nothing suitable stays empty rather than forcing a shortage."""
    left = {k: dict(v) for k, v in ctx.stock.items()}
    _take(left, lunch, ctx)
    used = set(lunch)
    bf = [i for i in dict.fromkeys(breakfast or []) if i in RECIPES and i not in used]
    if not (bf and force_breakfast) and not _fits(bf, ctx, left):    # the owner's own pick is kept even if it needs shopping
        bf = _pick_breakfast(ctx, used | set(avoid), left) or _pick_breakfast(ctx, used, left)     # `avoid`: other options' dishes, if possible
    if not bf and allow_buy:                      # nothing in stock makes a breakfast: suggest one that needs a small shop
        bf = _pick_breakfast(ctx, used | set(avoid), left, 2) or _pick_breakfast(ctx, used, left, 2)
    _take(left, bf, ctx)
    used |= set(bf)
    dn = [i for i in dict.fromkeys(dinner or []) if i in RECIPES and i not in used][:3]
    if not (dn and force_dinner) and not _fits(dn, ctx, left):
        dn = _pick_dinner(ctx, used | set(avoid), left, lunch) or _pick_dinner(ctx, used, left, lunch)
        if not dn and allow_buy:
            dn = _pick_dinner(ctx, used | set(avoid), left, lunch, 2) or _pick_dinner(ctx, used, left, lunch, 2)
    return {"breakfast": bf, "lunch": list(lunch), "dinner": dn}


def with_day(p: Proposal, ctx: PlanContext, breakfast=None, dinner=None, avoid: set[str] = frozenset()) -> Proposal:
    """Turn a lunch proposal into a whole-day one. Breakfast and dinner come from stock first; only if stock can't
    make one do they suggest a dish needing at most two items from the shop, and those join the gaps."""
    flat = lambda m: list(dict.fromkeys(i for k in MEAL_ORDER for i in m[k] if i))        # noqa: E731
    stock_only = plan_day(p.recipe_ids, ctx, breakfast, dinner, avoid=avoid)
    meals = plan_day(p.recipe_ids, ctx, breakfast, dinner, avoid=avoid, allow_buy=True)
    union = flat(meals)
    lunch_gaps = {g["name"] for g in p.gaps}
    extra = [g["name"] for g in inv.gaps(_needs(union, ctx), ctx.stock) if g["name"] not in lunch_gaps]
    return dataclasses.replace(p, recipe_ids=union, meals=meals, stock_meals=stock_only, extra_buy=extra)


def label_options(picks: list[Proposal], ctx: PlanContext) -> list[Proposal]:
    """Give each option its own reason to be picked, so three options read as three different choices."""
    if len(picks) == 1:
        return [dataclasses.replace(picks[0], label="Best fit")]
    scored = {
        "Saves the most food": [_urgency_of(p.recipe_ids, ctx) for p in picks],
        "Quickest": [-sum(RECIPES[r]["prep"] for r in p.recipe_ids) for p in picks],
        "Lightest": [sum(1 for r in p.recipe_ids if "light" in RECIPES[r]["tags"]) - sum(1 for r in p.recipe_ids if "heavy" in RECIPES[r]["tags"]) for p in picks]}
    labels: dict[int, str] = {}
    for name, vals in scored.items():
        order = sorted((i for i in range(len(picks)) if i not in labels), key=lambda i: (-vals[i], i))
        if order and (vals[order[0]] > min(vals) or name == "Saves the most food"):
            labels[order[0]] = name
    return [dataclasses.replace(p, label=labels.get(i, "Something different")) for i, p in enumerate(picks)]


def _left_after(ctx: PlanContext, taken: list[str]) -> PlanContext:
    left = {k: dict(v) for k, v in ctx.stock.items()}
    _take(left, taken, ctx)
    return dataclasses.replace(ctx, stock=left)


def breakfast_options(ctx: PlanContext, taken: list[str], n: int = 3) -> list[Proposal]:
    ctx2, used, cands = _left_after(ctx, taken), set(taken), []
    for max_gaps in (2, 4, 99):                 # prefer what's nearly makeable, but never leave the owner without a list
        cands = []
        for rid, r in RECIPES.items():
            if r["course"] != "breakfast" or rid in used or rid in ctx.exclude_ids or not allowed(rid, ctx2):
                continue
            n_gaps = _n_gaps([rid], ctx2, ctx2.stock)
            if n_gaps > max_gaps:
                continue
            rep = _repeat_days(rid, ctx)
            cands.append(((n_gaps, -_urgency_of([rid], ctx2), 1 if rep is not None and rep <= 3 else 0, r["prep"], rid), rid))
        if len(cands) >= n:
            break
    picks = [enrich([rid], ctx2) for _, rid in sorted(cands)[:n]]
    return label_options(picks, ctx2) if picks else []


def dinner_options(ctx: PlanContext, taken: list[str], lunch: list[str], n: int = 3) -> list[Proposal]:
    ctx2 = _left_after(ctx, taken)
    picks, mains = [], set()
    for max_gaps in (2, 99):
        for _, ids in _dinner_candidates(ctx, set(taken), ctx2.stock, lunch or taken[:1] or ["roti"], max_gaps=max_gaps):
            if ids[0] in mains:
                continue
            mains.add(ids[0])
            picks.append(enrich(ids, ctx2))
            if len(picks) == n:
                break
        if len(picks) == n:
            break
    picks = sorted(picks, key=lambda p: len(p.gaps))
    return label_options(picks, ctx2) if picks else []


def day_name(meals: dict) -> str:
    return " · ".join(f"{m.title()}: {menu_name(meals[m])}" for m in ("breakfast", "lunch", "dinner") if meals.get(m))


# ---------------------------------------------------------------- heuristic
def _no_heat(ctx: PlanContext) -> bool:
    """Nobody is cooking, or there is no way to: only no-cook dishes are possible."""
    return bool(ctx.flags.get("cook_off")) or "stove_broken" in ctx.constraints


def _mainable(ctx: PlanContext) -> set[str]:
    if _no_heat(ctx):
        return {"side", "breakfast"}
    if ctx.flags.get("fasting"):
        return {"vrat", "sabzi", "side"}
    return {"sabzi", "dal", "one_pot", "breakfast"}


def _pair_courses(main_course: str, ctx: PlanContext) -> list[tuple[str, bool]]:
    """Companion courses to try after the main: (course, required)."""
    if _no_heat(ctx) or ctx.flags.get("fasting"):
        return [("side", False)]
    return {"sabzi": [("carb", True), ("dal", False)], "dal": [("carb", True), ("sabzi", False)],
            "one_pot": [("side", False)], "breakfast": []}.get(main_course, [])


def _urgency_of(ids: list[str], ctx: PlanContext, skip: set[str] = frozenset()) -> float:
    needs = _needs(ids, ctx)
    return sum(_urgency_weight(ctx.stock[i]["days_left"]) for i, n in needs.items()
               if i in ctx.stock and i not in skip and ctx.stock[i]["qty"] >= n["qty"])


def _build_menu(main: str, ctx: PlanContext, max_gaps: int = 2) -> list[str] | None:
    gaps = inv.gaps(_needs([main], ctx), ctx.stock)
    if len(gaps) > max_gaps:
        return None
    ids = [main]
    # remaining stock after the main, so companions must be fully makeable from what is left
    left = {k: dict(v) for k, v in ctx.stock.items()}
    for item, n in _needs([main], ctx).items():
        if item in left:
            left[item]["qty"] = max(0.0, left[item]["qty"] - n["qty"])
    for course, required in _pair_courses(RECIPES[main]["course"], ctx):
        best = None
        for rid, r in RECIPES.items():
            if r["course"] != course or rid in ids or not allowed(rid, ctx):
                continue
            if inv.gaps(_needs([rid], ctx), left):
                continue
            gain = _urgency_of([rid], ctx, skip={i for x in ids for i in RECIPES[x]["needs"]})
            key = (-gain, 0 if rid in ("roti",) else 1, rid)
            if best is None or key < best[0]:
                best = (key, rid, gain)
        if best and (required or best[2] > 0) and len(ids) < 3:
            ids.append(best[1])
            for item, n in _needs([best[1]], ctx).items():
                if item in left:
                    left[item]["qty"] = max(0.0, left[item]["qty"] - n["qty"])
    return ids


def heuristic_propose(ctx: PlanContext, n: int = 3, day: bool = True) -> Proposals:
    """Greedy selection by *marginal* spoilage coverage, so the options together use up as much of what is
    about to spoil as possible (not three menus that all use the same tomatoes)."""
    likes = {norm(i) for i in ctx.preferences.get("likes", [])}
    avoid = {m["note"] for m in ctx.memory if m["kind"] == "avoid_dish"}
    recent_quick = any(m["kind"] == "constraint" and "time" in m["note"] for m in ctx.memory)
    mainable = _mainable(ctx)
    def candidates(max_gaps: int) -> list:
        out = []
        for rid, r in RECIPES.items():
            if r["course"] not in mainable or rid in ctx.exclude_ids or not allowed(rid, ctx):
                continue
            ids = _build_menu(rid, ctx, max_gaps)
            if not ids:
                continue
            gaps = inv.gaps(_needs(ids, ctx), ctx.stock)
            uses = {i: _urgency_weight(ctx.stock[i]["days_left"]) for i, nd in _needs(ids, ctx).items()
                    if i in ctx.stock and ctx.stock[i]["qty"] >= nd["qty"]}
            rep = _repeat_days(rid, ctx)
            fixed = -len(gaps) * 5
            fixed -= 4 if rep is not None and rep <= 3 else 2 if rep is not None and rep <= 7 else 0
            fixed += 1 if likes & set(r["needs"]) else 0
            fixed += 1 if recent_quick and r["prep"] <= 30 else 0
            fixed += 2 if ctx.light and "light" in r["tags"] else 0
            fixed -= 6 if rid in avoid else 0
            fixed += 0.3 * (len(ids) - 1)          # a fuller meal beats a lone dish, all else equal
            out.append((ids, not gaps, uses, fixed))
        return out

    cands = candidates(2) or candidates(99)         # never leave the owner without a list: a bigger shop beats nothing

    picked: list[list[str]] = []
    covered: set[str] = set()
    while cands and len(picked) < n:
        # never offer the same set of dishes twice, and prefer variety between the options
        cands = [c for c in cands if all(set(c[0]) != set(p) for p in picked)]
        if not cands:
            break

        def gain(c):
            ids, feasible, uses, fixed = c
            urgency = sum(w * (1.0 if i not in covered else 0.15) for i, w in uses.items())
            overlap = sum(1 for d in ids if RECIPES[d]["course"] != "carb" and any(d in p for p in picked))
            return (int(feasible), urgency * 2 + fixed - 3 * overlap, ids[0])
        best = max(cands, key=gain)
        cands.remove(best)
        picked.append(best[0])
        covered |= {i for i, w in best[2].items() if w > 0}
    picks, seen = [], set()
    for ids in picked:                                  # breakfast and dinner differ between options where the stock allows
        if not day:                                     # one meal at a time: lunch options only
            picks.append(enrich(ids, ctx))
            continue
        p = with_day(enrich(ids, ctx), ctx, avoid=seen)
        seen |= set(p.meals["breakfast"]) | set(p.meals["dinner"])
        picks.append(p)
    picks = label_options(picks, ctx)
    return Proposals(picks, tradeoffs(picks, ctx), "heuristic")


def tradeoffs(picks: list[Proposal], ctx: PlanContext) -> list[str]:
    notes = []
    for p in picks:
        if p.repeat_days_ago is not None and p.repeat_days_ago <= 7:
            main = RECIPES[p.recipe_ids[0]]["name"]
            notes.append(f"{main} was served {p.repeat_days_ago} day(s) ago; I allowed the repeat because it uses "
                         "food that would otherwise spoil." if "Uses up" in p.reason else
                         f"{main} was served {p.repeat_days_ago} day(s) ago (repeat).")
    covered = {i for p in picks for i in _needs(p.recipe_ids, ctx)}
    for name, s in ctx.stock.items():
        if s["days_left"] is not None and s["days_left"] <= 1 and name not in covered:
            notes.append(f"{name} is nearly out of date but no option uses it; tell me if you want a dish built "
                         "around it.")
    return notes


# ---------------------------------------------------------------- Claude
PROPOSE_TOOL = {
    "name": "propose_menu",
    "description": "Propose 2-3 alternative plans for tomorrow. Each plan has lunch (1-3 dishes), optionally breakfast and dinner.",
    "input_schema": {
        "type": "object",
        "properties": {
            "menus": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                "type": "object",
                "properties": {
                    "dish_ids": {"type": "array", "minItems": 1, "maxItems": 3,
                                 "items": {"type": "string", "enum": sorted(RECIPES)},
                                 "description": "LUNCH: main dish first, then companions (e.g. roti, dal)."},
                    "breakfast_ids": {"type": "array", "maxItems": 1, "items": {"type": "string", "enum": sorted(RECIPES)},
                                      "description": "Optional breakfast dish, made from stock left after lunch."},
                    "dinner_ids": {"type": "array", "maxItems": 3, "items": {"type": "string", "enum": sorted(RECIPES)},
                                   "description": "Optional lighter dinner, made from stock left after lunch and breakfast."},
                    "reason": {"type": "string", "description": "One friendly sentence."}},
                "required": ["dish_ids", "reason"]}},
        },
        "required": ["menus"],
    },
}

SYSTEM = """You plan tomorrow's home-cooked meal for an Indian household.
Priorities, in order: (1) use ingredients closest to spoiling, (2) do not repeat a recent dish unless it is needed to
avoid waste, (3) honour diet, fasting, guests, dislikes and the owner's feedback, (4) tasty, balanced and healthy
(e.g. a sabzi or dal with roti or rice). Offer 2-3 meals that differ from each other. Only choose dishes from the
recipe book. Plan breakfast, lunch and dinner separately: lunch is the main meal (dish_ids); breakfast_ids and
dinner_ids are optional and must be makeable from what is left after the earlier meals; dinner should be lighter and
differ from lunch. Prefer meals fully makeable from the stock. Respect every constraint (broken stove => no stove dishes;
fasting => vrat dishes only; cook off => no-cook dishes). Never invent ingredients."""


class ClaudePlanner:
    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def propose(self, ctx: PlanContext, n: int = 3, day: bool = True) -> Proposals:
        stock = "\n".join(f"- {k}: {fmt_qty(v['qty'], v['unit'])}, days left: {v['days_left']}"
                          for k, v in sorted(ctx.stock.items(), key=lambda kv: (kv[1]['days_left'] is None,
                                                                              kv[1]['days_left'] or 0)))
        pool = [rid for rid in RECIPES if allowed(rid, ctx)]
        book = "\n".join(f"- {rid}: {RECIPES[rid]['name']} [{RECIPES[rid]['course']}] needs " +
                         ", ".join(f"{i} {fmt_qty(*q)}" for i, q in RECIPES[rid]["needs"].items()) +
                         f" | prep={RECIPES[rid]['prep']}min" for rid in pool)
        recent = "\n".join(f"- {m['day']}: {m['dish']}" for m in ctx.recent_meals) or "- none"
        user = (f"Cooking day: {ctx.cook_day}\nServings multiplier: x{ctx.scale:g} (recipes are for 4)\n"
                f"Per-day flags: {ctx.flags}\nHousehold preferences: {ctx.preferences}\n"
                f"Active constraints: {ctx.constraints}\nLong-term notes: {[m['note'] for m in ctx.memory]}\n"
                f"Owner feedback so far: {ctx.feedback}\nMains already rejected: {sorted(ctx.exclude_ids)}\n\n"
                f"Confirmed stock (soonest to spoil first):\n{stock}\n\nRecent meals:\n{recent}\n\n"
                f"Allowed recipes (quantities are for 4 servings):\n{book}")
        resp = self.client.messages.create(
            model=self.model, max_tokens=900, system=SYSTEM, tools=[PROPOSE_TOOL],
            tool_choice={"type": "tool", "name": "propose_menu"},
            messages=[{"role": "user", "content": user}])
        picks: list[Proposal] = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            for m in block.input.get("menus", []):
                ids = [i for i in dict.fromkeys(m.get("dish_ids", [])) if i in RECIPES and allowed(i, ctx)]
                if ids and ids[0] not in ctx.exclude_ids and all(p.recipe_ids[0] != ids[0] for p in picks):
                    p = enrich(ids[:3], ctx, m.get("reason"))
                    picks.append(with_day(p, ctx, m.get("breakfast_ids"), m.get("dinner_ids")) if day else p)
        if not picks:
            raise ValueError("Claude returned no valid menus")
        picks = label_options(picks[:n], ctx)
        return Proposals(picks, tradeoffs(picks, ctx), "claude")


class Planner:
    """Claude when configured, heuristics otherwise (and on any Claude failure)."""

    def __init__(self, claude: ClaudePlanner | None = None):
        self.claude = claude
        self.last_source = "heuristic"

    def propose(self, ctx: PlanContext, n: int = 3, day: bool = True) -> Proposals:
        if self.claude:
            try:
                out = self.claude.propose(ctx, n, day)
                self.last_source = "claude"
                return out
            except Exception:
                pass
        self.last_source = "heuristic"
        return heuristic_propose(ctx, n, day)

    def meal_options(self, meal: str, ctx: PlanContext, taken: list[str], lunch: list[str] | None = None, n: int = 3) -> list[Proposal]:
        """Options for ONE meal, planned from the stock left after the meals already chosen."""
        if meal == "breakfast":
            return breakfast_options(ctx, taken, n)
        if meal == "dinner":
            return dinner_options(ctx, taken, lunch or [], n)
        return self.propose(_left_after(ctx, taken), n, day=False).items
