"""Menu planning (S2). Claude proposes; deterministic code validates and computes gaps.

Claude may only pick dishes from the recipe book (by id), so ingredient lists and quantities are never
hallucinated. A heuristic planner is the fallback and the offline mode.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import inventory as inv
from .nlu import find_items, norm, tokens
from .recipes import ITEMS, RECIPES, fmt_qty


@dataclass
class PlanContext:
    cook_day: str
    stock: dict[str, dict]                      # confirmed, non-spoiled: name -> {qty, unit, days_left}
    recent_meals: list[dict] = field(default_factory=list)   # {day, dish_id, dish}
    preferences: dict = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)     # e.g. stove_broken, time_short (today)
    memory: list[dict] = field(default_factory=list)         # long-term notes
    feedback: list[str] = field(default_factory=list)        # owner's "something else" input
    exclude_ids: set[str] = field(default_factory=set)


@dataclass
class Proposal:
    recipe_id: str
    name: str
    reason: str
    feasible: bool
    gaps: list[dict]
    repeat_days_ago: int | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Proposals:
    items: list[Proposal]
    tradeoffs: list[str]
    source: str


def _excluded_items(ctx: PlanContext) -> set[str]:
    out = {norm(i) for i in ctx.preferences.get("dislikes", [])}
    for fb in ctx.feedback:
        toks = tokens(fb)
        if {"no", "not", "nahi", "without", "avoid", "नहीं"} & set(toks):
            out |= set(find_items(toks))
    return out


def _violates(rid: str, ctx: PlanContext) -> bool:
    r = RECIPES[rid]
    if rid in ctx.exclude_ids:
        return True
    if "stove_broken" in ctx.constraints and r["stove"]:
        return True
    if "time_short" in ctx.constraints and r["prep"] > 25:
        return True
    return bool(_excluded_items(ctx) & set(r["needs"]))


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


def enrich(rid: str, ctx: PlanContext, reason: str | None = None) -> Proposal:
    r = RECIPES[rid]
    gaps = inv.gaps(inv.needs_for([rid]), ctx.stock)
    used_urgent = [i for i in r["needs"] if i in ctx.stock and ctx.stock[i]["days_left"] is not None
                   and ctx.stock[i]["days_left"] <= 2 and ctx.stock[i]["qty"] >= r["needs"][i][0]]
    if reason is None:
        if used_urgent:
            when = {ctx.stock[i]["days_left"] for i in used_urgent}
            soon = "tomorrow" if min(when) <= 1 else "within 2 days"
            reason = f"Uses {', '.join(used_urgent)} (expiring {soon})."
        else:
            reason = "Uses what you already have."
    return Proposal(rid, r["name"], reason, not gaps, gaps, _repeat_days(rid, ctx))


def heuristic_propose(ctx: PlanContext, n: int = 3) -> Proposals:
    """Greedy selection by *marginal* spoilage coverage, so the set of options together uses up as much
    of what is about to spoil as possible (not three dishes that all use the same tomatoes)."""
    likes = {norm(i) for i in ctx.preferences.get("likes", [])}
    avoid = {m["note"] for m in ctx.memory if m["kind"] == "avoid_dish"}
    recent_quick = any(m["kind"] == "constraint" and "time" in m["note"] for m in ctx.memory)
    cands = []
    for rid, r in RECIPES.items():
        if _violates(rid, ctx):
            continue
        gaps = inv.gaps(inv.needs_for([rid]), ctx.stock)
        if len(gaps) > 2:
            continue
        uses = {i: _urgency_weight(ctx.stock[i]["days_left"]) for i, (q, _) in r["needs"].items()
                if i in ctx.stock and ctx.stock[i]["qty"] >= q}
        rep = _repeat_days(rid, ctx)
        fixed = -len(gaps) * 5
        fixed -= 4 if rep is not None and rep <= 3 else 2 if rep is not None and rep <= 7 else 0
        fixed += 1 if likes & set(r["needs"]) else 0
        fixed += 1 if recent_quick and r["prep"] <= 30 else 0
        fixed -= 6 if rid in avoid else 0
        cands.append((rid, not gaps, uses, fixed))

    picked: list[str] = []
    covered: set[str] = set()
    while cands and len(picked) < n:
        def gain(c):
            rid, feasible, uses, fixed = c
            urgency = sum(w * (1.0 if i not in covered else 0.15) for i, w in uses.items())
            return (int(feasible), urgency * 2 + fixed, rid)
        best = max(cands, key=gain)
        cands.remove(best)
        picked.append(best[0])
        covered |= {i for i, w in best[2].items() if w > 0}
    picks = [enrich(rid, ctx) for rid in picked]
    return Proposals(picks, tradeoffs(picks, ctx), "heuristic")


def tradeoffs(picks: list[Proposal], ctx: PlanContext) -> list[str]:
    notes = []
    for p in picks:
        if p.repeat_days_ago is not None and p.repeat_days_ago <= 7:
            notes.append(f"{p.name} was served {p.repeat_days_ago} day(s) ago; I allowed the repeat because "
                         f"it uses food that would otherwise spoil." if "expiring" in p.reason else
                         f"{p.name} was served {p.repeat_days_ago} day(s) ago (repeat).")
    covered = {i for p in picks for i in RECIPES[p.recipe_id]["needs"]}
    for name, s in ctx.stock.items():
        if s["days_left"] is not None and s["days_left"] <= 1 and name not in covered:
            notes.append(f"{name} expires tomorrow but no option uses it; tell me if you want a dish built around it.")
    return notes


# ---------- Claude ----------
PROPOSE_TOOL = {
    "name": "propose_menu",
    "description": "Pick 2-3 dishes from the recipe book for tomorrow.",
    "input_schema": {
        "type": "object",
        "properties": {
            "dishes": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
                "type": "object",
                "properties": {"recipe_id": {"type": "string", "enum": sorted(RECIPES)},
                               "reason": {"type": "string", "description": "One sentence, plain English."}},
                "required": ["recipe_id", "reason"]}},
        },
        "required": ["dishes"],
    },
}

SYSTEM = """You plan tomorrow's home-cooked meal for an Indian household.
Priorities, in order: (1) use ingredients closest to spoiling, (2) do not repeat a recent dish unless it is
needed to avoid waste, (3) honour dislikes, diet and the owner's feedback, (4) tasty and healthy.
Only choose dishes from the recipe book given. Prefer dishes that are fully makeable from the stock. Respect
every constraint (e.g. broken stove => no stove dishes). Never invent ingredients."""


class ClaudePlanner:
    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def propose(self, ctx: PlanContext, n: int = 3) -> Proposals:
        stock = "\n".join(f"- {k}: {fmt_qty(v['qty'], v['unit'])}, days left: {v['days_left']}"
                          for k, v in sorted(ctx.stock.items(), key=lambda kv: (kv[1]['days_left'] is None,
                                                                              kv[1]['days_left'] or 0)))
        book = "\n".join(f"- {rid}: {r['name']} | needs " +
                         ", ".join(f"{i} {fmt_qty(*q)}" for i, q in r["needs"].items()) +
                         f" | stove={r['stove']} | prep={r['prep']}min" for rid, r in RECIPES.items())
        recent = "\n".join(f"- {m['day']}: {m['dish']}" for m in ctx.recent_meals) or "- none"
        user = (f"Cooking day: {ctx.cook_day}\n\nConfirmed stock (soonest to spoil first):\n{stock}\n\n"
                f"Recent meals:\n{recent}\n\nPreferences: {ctx.preferences}\nToday's constraints: {ctx.constraints}\n"
                f"Long-term notes: {[m['note'] for m in ctx.memory]}\nOwner feedback so far: {ctx.feedback}\n"
                f"Already rejected: {sorted(ctx.exclude_ids)}\n\nRecipe book:\n{book}")
        resp = self.client.messages.create(
            model=self.model, max_tokens=800, system=SYSTEM, tools=[PROPOSE_TOOL],
            tool_choice={"type": "tool", "name": "propose_menu"},
            messages=[{"role": "user", "content": user}])
        picks = []
        for block in resp.content:
            if block.type == "tool_use":
                for d in block.input.get("dishes", []):
                    rid = d.get("recipe_id")
                    if rid in RECIPES and not _violates(rid, ctx) and all(p.recipe_id != rid for p in picks):
                        picks.append(enrich(rid, ctx, d.get("reason")))
        if not picks:
            raise ValueError("Claude returned no valid dishes")
        picks = picks[:n]
        return Proposals(picks, tradeoffs(picks, ctx), "claude")


class Planner:
    """Claude when configured, heuristics otherwise (and on any Claude failure)."""

    def __init__(self, claude: ClaudePlanner | None = None):
        self.claude = claude

    def propose(self, ctx: PlanContext, n: int = 3) -> Proposals:
        if self.claude:
            try:
                return self.claude.propose(ctx, n)
            except Exception:
                pass
        return heuristic_propose(ctx, n)
