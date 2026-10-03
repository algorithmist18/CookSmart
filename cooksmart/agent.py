"""The CookSmart agent: the S1-S8 state machine.

Claude (via Planner/NLU) proposes and understands; everything that has consequences (stock, money,
what the cook is told) is decided here, in code, behind guards.

Plan states:  review -> (approval | held) -> ordered -> ready -> briefed -> closing -> closed
"""
from __future__ import annotations

import datetime as dt
import random
import re

from . import callresult, cookbrief, cookmsgs, guards, repo
from . import inventory as inv
from .channels import MessageChannel
from .db import DB
from .nlu import NLU
from . import profile as prof
from .planner import PlanContext, Planner, plan_day, use_within
from .providers.calls import CallProvider, CallRequest
from .providers.dispatch import DispatchProvider
from .providers.grocery import GroceryProvider
from .providers.payment import PaymentProvider
from .providers.speech import LOW_CONFIDENCE, SpeechProvider, Transcript
from .providers.voice import VoiceVerifier
from . import daystory
from .recipes import ITEMS, RECIPES, fmt_qty

NIGHT_MINUTES_LEFT = 630     # ~21:30 order -> 08:00 cook arrival
MORNING_MINUTES_LEFT = 30
PROBLEMS = ("used_up", "remaining", "low", "spoiled", "cannot_cook")

CHAT_REPLIES = {
    "thanks": "🙂 Anytime.", "hello": "👋 Hi! Say *help* to see what I can do, or tell me about tomorrow's meals.",
    "night": "🌙 Good night!", "pause": "👍 Sure, take your time. I'll wait.", "bye": "👋 See you.",
}

HELP = (
    "👋 *I'm CookSmart.* Here's what you can tell me:\n"
    "• *1*, *2*, *3*, a dish name, or *skip*: choose breakfast, then lunch, then dinner\n"
    "• *breakfast poha, lunch dal rice*: name several meals at once\n"
    "• *something else*: I'll propose different meals\n"
    "• *cream 100 ml*, *no tomatoes*, *all good*: fix what's in the kitchen\n"
    "• *6 guests tomorrow*, *fasting tomorrow*, *cook is off tomorrow*\n"
    "• *veg only*, *non veg ok*, *jain*, *no dairy*, *family of 5*\n"
    "• *tell cook: kam mirch*: I'll pass your message on\n"
    "• *approve* / *no*: order decisions · *mode auto* / *mode approve* · *cap 400*\n"
    "• *change menu*: start over for tomorrow"
)


def _plus(day: str, n: int) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=n)).isoformat()


def _names(ids: list[str]) -> str:
    return " + ".join(RECIPES[i]["name"] for i in ids)


def _meals_for(proposals: list[dict], ids: list[str]) -> dict:
    """Breakfast/lunch/dinner for a chosen set of dishes: merge the proposals that were picked whole; a dish the owner
    asked for by name is lunch (nothing else is invented around it)."""
    out: dict[str, list[str]] = {"breakfast": [], "lunch": [], "dinner": []}
    for p in proposals:
        if p.get("meals") and set(p["recipe_ids"]) <= set(ids):
            for m, dishes in p["meals"].items():
                out[m] += [d for d in dishes if not any(d in v for v in out.values())]
    out["lunch"] += [d for d in ids if not any(d in v for v in out.values())]
    return out


def _flat(proposals: list[dict], picks: list[int]) -> list[str]:
    out: list[str] = []
    for n in picks:
        if 1 <= n <= len(proposals):
            out += [i for i in proposals[n - 1]["recipe_ids"] if i not in out]
    return out


class Agent:
    def __init__(self, db: DB, channel: MessageChannel, planner: Planner, nlu: NLU, speech: SpeechProvider,
                 grocery: GroceryProvider, dispatch: DispatchProvider, payment: PaymentProvider,
                 voice: VoiceVerifier, caller: CallProvider | None = None):
        self.db, self.channel, self.planner, self.nlu = db, channel, planner, nlu
        self.speech, self.grocery, self.dispatch = speech, grocery, dispatch
        self.payment, self.voice = payment, voice
        self.caller = caller          # the Gnani voice agent that phones the cook; None = chat only

    # ------------------------------------------------------------------ helpers
    def _h(self, hid: str) -> dict:
        h = repo.get_household(self.db, hid)
        if not h:
            raise KeyError(f"unknown household {hid}")
        return h

    def _say(self, hid: str, text: str, buttons: list[str] | None = None) -> None:
        self.channel.send_owner(hid, text, buttons)

    def _cook_say(self, hid: str, msg) -> None:
        self.channel.send_cook(hid, msg)

    def _scale(self, plan: dict) -> float:
        return float(plan["flags"].get("scale", 1.0))

    def _make_flags(self, h: dict, base: dict) -> dict:
        guests = int(base.get("guests", 0))
        return {"guests": guests, "fasting": bool(base.get("fasting")), "light": bool(base.get("light")),
                "cook_off": bool(base.get("cook_off")), "scale": (h["family_size"] + guests) / 4}

    def _flag_lines(self, flags: dict, h: dict) -> list[str]:
        out = []
        if flags.get("guests"):
            out.append(f"👥 Planning for *{h['family_size'] + flags['guests']} people* "
                       f"({flags['guests']} guests).")
        if flags.get("fasting"):
            out.append("🪔 *Fasting day*: vrat dishes only.")
        if flags.get("cook_off"):
            out.append("🏖️ *Cook is off tomorrow*: only no-cook options.")
        return out

    def _ctx(self, hid: str, cook_day: str, flags=None, constraints=None, feedback=None, exclude=None) -> PlanContext:
        h = self._h(hid)
        return PlanContext(
            cook_day=cook_day,
            stock=inv.available(self.db, hid, h["sim_date"], cook_day),
            recent_meals=repo.recent_meals(self.db, hid, _plus(cook_day, -7)),
            preferences=h["preferences"], flags=dict(flags or {}), constraints=list(constraints or []),
            memory=repo.list_memory(self.db, hid), feedback=list(feedback or []),
            exclude_ids=set(exclude or []), today=h["sim_date"])

    def _plan_ctx(self, hid: str, plan: dict, **kw) -> PlanContext:
        return self._ctx(hid, plan["day"], flags=plan["flags"], **kw)

    def _minutes_left(self, h: dict, plan: dict) -> int:
        return NIGHT_MINUTES_LEFT if h["sim_date"] < plan["day"] else MORNING_MINUTES_LEFT

    def _upcoming(self, h: dict, plan: dict | None) -> bool:
        return bool(plan) and plan["state"] != "closed" and plan["day"] > h["sim_date"]

    def _day_text(self, plan: dict, bold: bool = False) -> str:
        """All three meals, one per line; a skipped meal says so."""
        m = daystory.meals_of(plan)
        return "\n".join(f"{daystory.ICON[k]} {k.title()}: " + ((f"*{_names(m[k])}*" if bold else _names(m[k])) if m[k] else "skipped")
                         for k in daystory.MEALS)

    def _fmt_stage_props(self, props: list[dict], stage: str, avail: dict, scale: float) -> str:
        lines = []
        for n, p in enumerate(props, 1):
            have = [i for i in inv.needs_for(p["recipe_ids"], scale) if i in avail and i not in {g["name"] for g in p["gaps"]}]
            parts = [f"*{n} · {p.get('label') or 'Option'}*", f"{daystory.ICON[stage]} {_names(p['recipe_ids'])}"]
            if p["reason"] and not p["reason"].startswith("Uses stock on hand"):
                parts.append(f"✨ {p['reason']}")
            if have:
                parts.append("📦 From your kitchen: " + ", ".join(have))
            parts.append("🛒 Buy: " + ", ".join(g["name"] for g in p["gaps"]) if p["gaps"] else "🛒 Nothing to buy")
            lines.append("\n".join(parts))
        return "\n\n".join(lines)

    def _send_proposals(self, hid: str, plan: dict, preface: str = "") -> None:
        props = plan["proposals"]
        head = (preface + "\n\n") if preface else ""
        if not props:
            self._say(hid, head + "🤷 No menu: nothing confirmed in stock. Update it (*tomato 4*) or say *all good*.")
            return
        h = self._h(hid)
        if plan["stage"]:
            stage = plan["stage"]
            text = (head + f"{daystory.ICON[stage]} *What do you want for {stage}?* Pick one:\n\n" +
                    self._fmt_stage_props(props, stage, inv.available(self.db, hid, h["sim_date"], plan["day"]), self._scale(plan)))
            text += (f"\n\n👉 Tap an option, or reply *1*, *2*, *3*. Or name your own dish. *skip* = no {stage}.")
            buttons = [f"Accept {n}" for n in range(1, len(props) + 1)] + [f"Skip {stage}", "Something else"]
            return self._say(hid, text, buttons)
        self._begin_stage(hid, plan["id"], "breakfast", preface)        # always step by step, never a whole-day list

    # ------------------------------------------------------------------ S1 + S2
    def nightly_review(self, hid: str) -> dict:
        h = self._h(hid)
        today, day = h["sim_date"], _plus(h["sim_date"], 1)
        previous = repo.latest_plan(self.db, hid)
        nxt = dict(h["preferences"].get("next", {}))
        flags = self._make_flags(h, nxt)
        if nxt:
            prefs = dict(h["preferences"])
            prefs.pop("next", None)
            repo.update_household(self.db, hid, preferences=prefs)
        plan = repo.new_plan(self.db, hid, day)
        repo.update_plan(self.db, hid, plan["id"], flags=flags)

        preface = []
        if previous and previous["state"] == "held" and previous["offer"]:
            o = previous["offer"]
            preface.append(f"🔔 *Reminder:* the grocery order for {_names(previous['chosen'])} "
                           f"(₹{o['total']:.0f}) was never approved. Nothing was bought.")
        soon = sorted((i for i in inv.list_items(self.db, hid) if inv.days_left(i, day) is not None and inv.days_left(i, day) <= 2
                       and not inv.is_spoiled(i, day)), key=lambda i: inv.days_left(i, day))
        if soon:
            ctx0 = PlanContext(cook_day=day, stock={}, today=today)
            preface.append("🧊 Eat soon:\n" + "\n".join(f"• {i['name']}: {use_within(ctx0, inv.days_left(i, day))}" for i in soon[:5]))
        preface += self._flag_lines(flags, h)
        spoiled = inv.spoiled_items(self.db, hid, day)
        if spoiled:
            preface.append("🗑️ *Probably gone off by tomorrow:* " + ", ".join(i["name"] for i in spoiled) +
                           ".\nPlease check and bin anything bad.")
        doubtful = inv.doubtful_items(self.db, hid, today, day)
        if doubtful:
            preface.append("🤔 *Not sure if you still have:* " +
                           ", ".join(f"{i['name']} {fmt_qty(i['qty'], i['unit'])}" for i in doubtful) +
                           ".\nI left these out of the plan. Reply *all good* if they're still there, or tell me what changed.")

        repo.audit(self.db, hid, "nightly_review", plan=plan["id"], flags=flags, doubtful=[i["name"] for i in doubtful])
        low = [i for i in inv.list_items(self.db, hid) if (inv.days_left(i, day) is not None and inv.days_left(i, day) <= 1)]
        repo.add_story(self.db, hid, plan["id"], "review", "Checked the fridge" + (
            ": " + ", ".join(i["name"] for i in low[:4]) + " going off soon." if low else ": all fresh."))
        self._begin_stage(hid, plan["id"], "breakfast", "\n".join(preface))        # meal by meal: breakfast first
        plan = repo.get_plan(self.db, hid, plan["id"])
        return plan

    # ------------------------------------------------------------------ understanding the owner
    def _owner_ctx(self, hid: str) -> dict:
        """What the chat is about right now, so "the second one" or "yes" can be read in context."""
        plan = repo.latest_plan(self.db, hid)
        if not plan:
            return {}
        ctx = {"state": plan["state"], "stage": plan["stage"], "meals": {m: [RECIPES[r]["name"] for r in v] for m, v in plan["meals"].items()},
               "options": [{"n": n, "label": p.get("label", ""), "dishes": [RECIPES[r]["name"] for r in p["recipe_ids"]], "buy": [g["name"] for g in p["gaps"]]}
                           for n, p in enumerate(plan["proposals"], 1)]}
        if plan["state"] in ("approval", "held") and plan["offer"]:
            ctx["order"] = f"{plan['offer']['store']}, ₹{plan['offer']['total']:.0f}"
        return ctx

    def _facts(self, hid: str) -> str:
        h, plan = self._h(hid), repo.latest_plan(self.db, hid)
        day = plan["day"] if plan else h["sim_date"]
        lines = ["Kitchen stock (name: quantity, eat within):"]
        for i in inv.list_items(self.db, hid):
            if i["qty"] > 0:
                left = inv.days_left(i, day)
                when = "" if left is None else (", spoiled" if inv.is_spoiled(i, day) else f", eat within {max(0, left + (dt.date.fromisoformat(day) - dt.date.fromisoformat(h['sim_date'])).days)} day(s)")
                lines.append(f"- {i['name']}: {fmt_qty(i['qty'], i['unit'])}{when}")
        if plan:
            m = daystory.meals_of(plan)
            lines.append("Menu so far: " + ("; ".join(f"{k}: {_names(v)}" for k, v in m.items() if v) or "nothing chosen yet"))
            if plan["stage"]:
                lines.append(f"Currently choosing: {plan['stage']}")
                for n, p in enumerate(plan["proposals"], 1):
                    lines.append(f"- option {n} ({p.get('label')}): {_names(p['recipe_ids'])}. {p['reason']} "
                                 + ("To buy: " + ", ".join(g["name"] for g in p["gaps"]) if p["gaps"] else "Nothing to buy"))
            lines.append(f"Plan state: {plan['state']}")
        for o in repo.list_orders(self.db, hid)[-2:]:
            lines.append(f"Order #{o['id']} from {o['store']}: {o['status']}, ETA {o['eta_minutes']} min, ₹{o['total']:.0f}")
        prefs = h["preferences"]
        lines.append(f"Diet: {prefs.get('diet', 'vegetarian')}; family size {h['family_size']}")
        allergies = sorted({a for m in prof.members(prefs) for a in m.get("allergies", [])})
        if allergies:
            lines.append("Allergies in the family: " + ", ".join(allergies))
        return "\n".join(lines)

    def _answer(self, hid: str, question: str) -> None:
        """Questions about the kitchen: Claude answers from the facts if available, otherwise simple rules do."""
        facts = self._facts(hid)
        text = self.nlu.answer(question, facts) or self._rule_answer(hid, question, facts)
        self._say(hid, text)

    def _rule_answer(self, hid: str, question: str, facts: str) -> str:
        from .nlu import find_items, tokens
        toks = set(tokens(question))
        stock = [l[2:] for l in facts.splitlines() if l.startswith("- ") and ": " in l and "option" not in l and "Order" not in l]
        def days_of(line: str) -> int:
            m = re.search(r"eat within (\d+)", line)
            return int(m.group(1)) if m else 99
        soon = sorted((l for l in stock if days_of(l) <= 3), key=days_of)
        asked_items = find_items(tokens(question))
        if asked_items:
            hits = [l for l in stock if l.split(":")[0] in asked_items]
            return ("📦 " + "\n📦 ".join(hits)) if hits else f"🤷 No {', '.join(asked_items)} in the fridge right now."
        if toks & {"expiring", "expire", "spoil", "spoiling", "going", "kharab", "fresh", "old", "first", "soon", "eat"}:
            return ("🧊 Eat soon:\n" + "\n".join(f"• {l}" for l in soon)) if soon else "🧊 Nothing is close to expiring."
        if toks & {"order", "delivery", "deliver", "groceries", "payment", "paid", "arrive", "aayega"}:
            o = [l for l in facts.splitlines() if l.startswith("Order")]
            return "🛒 " + o[-1] if o else "🛒 No order yet."
        if toks & {"menu", "plan", "planned", "cooking", "today", "tomorrow", "eat", "khana", "dinner", "lunch", "breakfast"}:
            m = next((l for l in facts.splitlines() if l.startswith("Menu so far")), "Nothing chosen yet")
            return "🍽️ " + m.replace("Menu so far: ", "")
        if toks & {"fridge", "stock", "have", "left", "bacha", "kitchen", "pantry"}:
            return "📦 In the fridge:\n" + "\n".join(f"• {l}" for l in stock) if stock else "📦 The fridge is empty. Say *fill the fridge*."
        return "I can tell you what's expiring, what's in the fridge, the menu, or your order. Try *what should I eat first?*"

    def restock(self, hid: str) -> None:
        """Fill the fridge with a fresh basic stock (for the demo, or after a real shop)."""
        h = self._h(hid)
        inv.seed(self.db, hid, h["sim_date"], inv.DEFAULT_STOCK)
        repo.audit(self.db, hid, "restock")
        self._say(hid, "🧺 Filled the fridge: tomato, spinach, paneer, onion, potato, dal, rice, atta, curd, peas and more. All fresh today.")
        self._after_stock_change(hid)

    def _stage_taken(self, plan: dict, stage: str) -> list[str]:
        return [d for m in daystory.MEALS if m != stage for d in plan["meals"].get(m, [])]

    def _begin_stage(self, hid: str, plan_id: int, stage: str, preface: str = "") -> None:
        """Offer options for one meal, planned from what the earlier meals left."""
        plan = repo.get_plan(self.db, hid, plan_id)
        ctx = self._plan_ctx(hid, plan, feedback=plan["feedback"], exclude=plan["excluded"])
        opts = self.planner.meal_options(stage, ctx, self._stage_taken(plan, stage), lunch=plan["meals"].get("lunch", []))
        plan = repo.update_plan(self.db, hid, plan_id, proposals=[p.as_dict() for p in opts], stage=stage,
                                notes=[], state="review")
        repo.audit(self.db, hid, "stage_options", plan=plan_id, stage=stage, options=[p.recipe_ids for p in opts])
        if not opts:                                                   # still ask: never skip a meal on the owner's behalf
            why = ("That's all I have for it from what's at home." if plan["excluded"] or plan["feedback"]
                   else "I can't make any from stock I'm sure of.")
            return self._say(hid, (preface + "\n\n" if preface else "") +
                             f"{daystory.ICON[stage]} *What do you want for {stage}?*\n{why} Name a dish and I'll order what's missing, "
                             f"or reply *skip*. Or say *fill the fridge*.", [f"Skip {stage}", "Fill the fridge"])
        self._send_proposals(hid, plan, preface)

    def _replan(self, hid: str, plan_id: int, preface: str = "") -> None:
        plan = repo.get_plan(self.db, hid, plan_id)
        if not plan["stage"]:                                          # a finished or older plan: start the meals again
            repo.update_plan(self.db, hid, plan_id, meals={})
        return self._begin_stage(hid, plan_id, plan["stage"] or "breakfast", preface)
        props = self.planner.propose(self._plan_ctx(hid, plan, feedback=plan["feedback"], exclude=plan["excluded"]))
        plan = repo.update_plan(self.db, hid, plan_id, proposals=[p.as_dict() for p in props.items],
                                notes=props.tradeoffs)
        repo.audit(self.db, hid, "replanned", plan=plan_id, source=props.source)
        self._send_proposals(hid, plan, preface)

    # ------------------------------------------------------------------ owner chat
    def handle_owner(self, hid: str, text: str) -> None:
        h = self._h(hid)
        repo.add_message(self.db, hid, "owner", "user", text)
        a = self.nlu.owner(text, self._owner_ctx(hid))
        act = a["action"]
        plan = repo.latest_plan(self.db, hid)

        if act == "mode":
            return self.set_settings(hid, order_mode=a["mode"])
        if act == "cap":
            return self.set_settings(hid, auto_cap=a["cap"])
        if act == "help":
            return self._say(hid, HELP)
        if act == "relay":
            return self._relay_to_cook(hid, a["text"])
        if act == "flags":
            return self._owner_flags(hid, a["flags"])
        if act == "prefs":
            return self._owner_prefs(hid, a["prefs"])
        if act == "profile":
            return self._owner_profile(hid, a)
        if act == "redo":
            return self._redo(hid)
        if act == "restock":
            return self.restock(hid)
        if act == "chat":
            return self._say(hid, CHAT_REPLIES[a["kind"]])
        if act == "ask":
            return self._answer(hid, a.get("text") or text)
        if act == "confirm_all":
            inv.confirm_all(self.db, hid, h["sim_date"])
            repo.audit(self.db, hid, "stock_confirmed_all")
            self._say(hid, "👍 Great, I've marked all current stock as confirmed.")
            return self._after_stock_change(hid)
        if act == "stock":
            return self._owner_stock_update(hid, a["updates"])
        if not plan or plan["state"] in ("closed",):
            return self._say(hid, "😴 There's no menu in progress. I'll start tonight's review after dinner. "
                                  "Type *help* to see what I can do.")

        state = plan["state"]
        if act == "meal_request" and state in ("review", "approval", "held", "ready"):
            return self._choose_meals(hid, plan, a["breakfast"], a["lunch"], a.get("dinner", []))
        if act == "skip" and state == "review" and plan["stage"]:
            meal = a.get("meal")
            if meal and meal != plan["stage"]:                      # "no dinner tonight" while still choosing lunch
                meals = {**plan["meals"], meal: []}
                repo.update_plan(self.db, hid, plan["id"], meals=meals)
                return self._say(hid, f"✅ {daystory.ICON[meal]} {meal.title()}: skipped. I won't ask about it.")
            return self._pick_for_stage(hid, plan, [])
        if act == "dish_request" and state in ("review", "approval", "held", "ready"):
            if state == "review" and plan["stage"]:
                return self._stage_dishes(hid, plan, a["dishes"])
            return self._choose(hid, plan, a["dishes"], reviewed=True)
        if act == "choose" and state == "review":
            ids = _flat(plan["proposals"], a["choices"])
            if ids:
                return self._pick(hid, plan, ids)
        if act == "yes" and state == "review" and plan["proposals"]:
            return self._pick(hid, plan, plan["proposals"][0]["recipe_ids"])
        if act == "yes" and state in ("approval", "held"):
            return self._approve(hid, plan)
        if act == "no" and state in ("approval", "held"):
            return self._decline(hid, plan)
        if act in ("no", "other") and state == "review":
            return self._reject(hid, plan, a.get("text", text))
        if act == "other":
            return self._say(hid, "🙂 I didn't catch that. Type *help* to see what I understand.")
        self._say(hid, f"👍 Noted.")

    def _relay_to_cook(self, hid: str, text: str) -> None:
        self._cook_say(hid, cookmsgs.render("relay", self._h(hid)["cook_language"], text=text))
        repo.audit(self.db, hid, "relay_to_cook", text=text)
        self._say(hid, f"📨 Sent to the cook: “{text}”.")

    def _owner_flags(self, hid: str, flags: dict) -> None:
        h = self._h(hid)
        plan = repo.latest_plan(self.db, hid)
        notes = {"guests": lambda v: f"{v} guest(s)" if v else "no guests", "fasting": lambda v: "fasting day" if v else "no fast",
                 "cook_off": lambda v: "cook is off"}
        said = ", ".join(notes[k](v) for k, v in flags.items() if k in notes)
        if self._upcoming(h, plan):
            merged = {**plan["flags"], **flags}
            merged = self._make_flags(h, merged)
            repo.update_plan(self.db, hid, plan["id"], flags=merged)
            repo.audit(self.db, hid, "flags_changed", flags=flags)
            if plan["state"] == "review":
                return self._replan(hid, plan["id"], f"📌 Noted: {said}. Re-planned:")
            return self._say(hid, f"📌 Noted: {said}. Your menu is already locked in, so reply *change menu* "
                                  "to redo it with this.")
        prefs = dict(h["preferences"])
        prefs["next"] = {**prefs.get("next", {}), **flags}
        repo.update_household(self.db, hid, preferences=prefs)
        repo.audit(self.db, hid, "flags_saved_for_next_plan", flags=flags)
        self._say(hid, f"📌 Noted for tomorrow night's plan: {said}.")

    def _owner_profile(self, hid: str, a: dict) -> None:
        h = self._h(hid)
        prefs = dict(h["preferences"])
        said = []
        for name, group in a.get("allergies", []):
            prefs = prof.with_allergy(prefs, name, group)
            said.append(f"{name.title()} is allergic to {group}: I'll never plan it and the cook will be warned")
        if a.get("style"):
            prefs["style"] = {**prefs.get("style", {}), **a["style"]}
            said.append("cooking style: " + ", ".join(f"{k} {v}" for k, v in a["style"].items()))
        if a.get("cook_channel"):
            prefs["cook_channel"] = a["cook_channel"]
            said.append("I'll " + ("phone the cook" if a["cook_channel"] == "call" else "message the cook") + " each morning")
        repo.update_household(self.db, hid, preferences=prefs)
        repo.audit(self.db, hid, "profile_changed", change={k: v for k, v in a.items() if k != "action"})
        plan = repo.latest_plan(self.db, hid)
        if a.get("allergies") and self._upcoming(self._h(hid), plan) and plan["state"] == "review":
            return self._replan(hid, plan["id"], "🛡️ Saved: " + "; ".join(said) + ". Re-planned:")
        self._say(hid, "🛡️ Saved: " + "; ".join(said) + ".")

    def _owner_prefs(self, hid: str, prefs_in: dict) -> None:
        h = self._h(hid)
        prefs = dict(h["preferences"])
        said = []
        if "diet" in prefs_in:
            prefs["diet"] = prefs_in["diet"]
            said.append(f"diet: {prefs_in['diet']}")
        if "lactose_free" in prefs_in:
            prefs["lactose_free"] = prefs_in["lactose_free"]
            said.append("no dairy" if prefs_in["lactose_free"] else "dairy is fine")
        if "dislike" in prefs_in:
            prefs["dislikes"] = sorted({*prefs.get("dislikes", []), *prefs_in["dislike"]})
            said.append("avoiding " + ", ".join(prefs_in["dislike"]))
        if "family_size" in prefs_in:
            repo.update_household(self.db, hid, family_size=prefs_in["family_size"])
            said.append(f"family of {prefs_in['family_size']}")
        repo.update_household(self.db, hid, preferences=prefs)
        repo.audit(self.db, hid, "preferences_changed", prefs=prefs_in)
        h = self._h(hid)
        plan = repo.latest_plan(self.db, hid)
        if self._upcoming(h, plan):
            repo.update_plan(self.db, hid, plan["id"], flags=self._make_flags(h, plan["flags"]))
            if plan["state"] == "review":
                return self._replan(hid, plan["id"], f"📌 Saved ({', '.join(said)}). Re-planned:")
        self._say(hid, f"📌 Saved: {', '.join(said)}. I'll use this from now on.")

    def _redo(self, hid: str) -> None:
        h = self._h(hid)
        plan = repo.latest_plan(self.db, hid)
        if not self._upcoming(h, plan):
            return self._say(hid, "There's no upcoming menu to change right now.")
        note = ""
        if plan["state"] == "ordered":
            note = " Your grocery order stays; what arrives goes into stock."
        repo.update_plan(self.db, hid, plan["id"], state="review", chosen=[], meals={}, offer=None, gaps=[], reviewed=False,
                         rejections=0, feedback=[], excluded=[], order_id=plan["order_id"])
        self._replan(hid, plan["id"], "🔄 Starting over for tomorrow." + note)

    def _owner_stock_update(self, hid: str, updates: list[dict]) -> None:
        h = self._h(hid)
        said = []
        for u in updates:
            item, qty = u["item"], u["qty"]
            cur = inv.get(self.db, hid, item)
            if qty is None:
                if cur and cur["qty"] > 0:
                    inv.set_qty(self.db, hid, item, cur["qty"], h["sim_date"])
                    said.append(f"{item}: confirmed {fmt_qty(cur['qty'], cur['unit'])}")
                else:
                    said.append(f"{item}: how much do you have? (e.g. *{item} 100 {ITEMS[item]['unit']}*)")
                continue
            exp = None
            if not cur or cur["qty"] <= 0:
                shelf = ITEMS[item]["shelf"]
                exp = _plus(h["sim_date"], shelf) if shelf else None
            inv.set_qty(self.db, hid, item, qty, h["sim_date"], expires_on=exp)
            said.append(f"{item}: {fmt_qty(qty, ITEMS[item]['unit'])}")
        repo.audit(self.db, hid, "owner_stock_update", updates=updates)
        self._say(hid, "🧊 Updated stock: " + "; ".join(said))
        self._after_stock_change(hid)

    def _after_stock_change(self, hid: str) -> None:
        plan = repo.latest_plan(self.db, hid)
        if not plan:
            return
        if plan["state"] == "review":
            self._replan(hid, plan["id"], "Re-planned with the updated stock.")
        elif plan["state"] in ("approval", "held", "ready") and plan["chosen"]:
            self._feasibility(hid, plan, hold=plan["state"] == "held")

    # ------------------------------------------------------------------ S3
    def _set_menu(self, hid: str, plan: dict, ids: list[str], meals: dict | None = None, **fields) -> dict:
        """Set today's dishes together with which meal each belongs to. Meals already served keep their dishes."""
        fields.setdefault("stage", "")
        meals = {m: list(meals.get(m, [])) for m in daystory.MEALS} if meals else _meals_for(plan["proposals"], ids)
        for m in plan["served"]:
            meals[m] = daystory.meals_of(plan)[m]
        union = [d for m in ("lunch", "dinner", "breakfast") for d in meals[m]]
        return repo.update_plan(self.db, hid, plan["id"], chosen=list(dict.fromkeys(union)), meals=meals, **fields)

    def _pick(self, hid: str, plan: dict, ids: list[str]) -> None:
        if plan["stage"]:
            return self._pick_for_stage(hid, plan, ids)
        self._choose(hid, plan, ids, reviewed=True)

    def _stage_dishes(self, hid: str, plan: dict, dishes: list[str]) -> None:
        """The owner named dishes instead of tapping an option: breakfast dishes are breakfast, the rest fill the meal
        being asked about (breakfast asks fall through to lunch)."""
        bf = [d for d in dishes if RECIPES[d]["course"] == "breakfast"]
        rest = [d for d in dishes if d not in bf]
        into_dinner = plan["stage"] == "dinner"
        self._choose_meals(hid, plan, bf, [] if into_dinner else rest, rest if into_dinner else [])

    def _pick_for_stage(self, hid: str, plan: dict, ids: list[str], preface: str = "", auto: bool = False) -> None:
        """The owner picked (or skipped) the current meal; move on to the next one, or finish the menu."""
        stage = plan["stage"]
        conflicts = prof.allergen_conflicts(ids, self._h(hid)["preferences"]) if ids else []
        if conflicts:
            c = conflicts[0]
            repo.audit(self.db, hid, "allergy_block", conflicts=conflicts)
            return self._say(hid, f"🚫 I won't plan *{RECIPES[c['recipe']]['name']}*: it has {c['item']} and "
                                  f"{', '.join(c['who'])} is allergic ({c['group']}). Pick another option.")
        meals = {**plan["meals"], stage: list(ids)}
        plan = repo.update_plan(self.db, hid, plan["id"], meals=meals, rejections=0, feedback=[], excluded=[])
        label = _names(ids) if ids else ("nothing planned" if auto else "skipped")
        done = f"✅ {daystory.ICON[stage]} {stage.title()}: {label}"
        preface = (preface + "\n" if preface else "") + done
        nxt = next((m for m in daystory.MEALS if m not in meals), None)
        if nxt:
            return self._begin_stage(hid, plan["id"], nxt, preface)
        union = [d for m in ("lunch", "dinner", "breakfast") for d in meals[m]]
        if not union:
            repo.update_plan(self.db, hid, plan["id"], stage="", meals={})
            return self._say(hid, preface + "\nNothing is planned for tomorrow. Say *change menu* to start again.")
        self._say(hid, preface)
        self._choose(hid, plan, list(dict.fromkeys(union)), reviewed=True, meals=meals)

    def _choose_meals(self, hid: str, plan: dict, breakfast: list[str], lunch: list[str], dinner: list[str]) -> None:
        """The owner named some meals. What they leave out comes from option 1."""
        named = {m: v for m, v in (("breakfast", breakfast), ("lunch", lunch), ("dinner", dinner)) if v}
        conflicts = prof.allergen_conflicts([d for v in named.values() for d in v], self._h(hid)["preferences"])
        if conflicts:                                     # a hard stop, whichever meal it was named for
            c = conflicts[0]
            repo.audit(self.db, hid, "allergy_block", conflicts=conflicts)
            return self._say(hid, f"🚫 I won't plan *{RECIPES[c['recipe']]['name']}*: it has {c['item']} and "
                                  f"{', '.join(c['who'])} is allergic ({c['group']}). Pick another option, or update the "
                                  "allergy first if it's wrong.")
        if plan["state"] != "review" or not plan["stage"]:             # already past choosing: the named meals replace the menu
            meals = {m: named.get(m, []) for m in daystory.MEALS}
            return self._choose(hid, plan, [d for m in ("lunch", "dinner", "breakfast") for d in meals[m]], reviewed=True, meals=meals)
        meals = {**plan["meals"], **named}
        plan = repo.update_plan(self.db, hid, plan["id"], meals=meals)
        nxt = next((m for m in daystory.MEALS if m not in meals), None)
        said = "\n".join(f"✅ {daystory.ICON[m]} {m.title()}: {_names(v)}" for m, v in named.items())
        if nxt:
            return self._begin_stage(hid, plan["id"], nxt, said)
        self._say(hid, said)
        self._choose(hid, plan, list(dict.fromkeys(d for m in ("lunch", "dinner", "breakfast") for d in meals[m])),
                     reviewed=True, meals=meals)

    def _choose(self, hid: str, plan: dict, ids: list[str], reviewed: bool, meals: dict | None = None) -> None:
        conflicts = prof.allergen_conflicts(ids, self._h(hid)["preferences"])
        if conflicts:                                     # a hard stop, not a warning
            c = conflicts[0]
            self._say(hid, f"🚫 I won't plan *{RECIPES[c['recipe']]['name']}*: it has {c['item']} and "
                           f"{', '.join(c['who'])} is allergic ({c['group']}). Pick another option, or update the "
                           "allergy first if it's wrong.")
            repo.audit(self.db, hid, "allergy_block", conflicts=conflicts)
            return
        plan = self._set_menu(hid, plan, ids, meals, reviewed=reviewed, offer=None, stage="")
        repo.audit(self.db, hid, "menu_chosen", plan=plan["id"], dishes=plan["chosen"], reviewed=reviewed)
        repo.add_story(self.db, hid, plan["id"], "plan", self._day_text(plan))
        self._say(hid, f"👍 Menu set:\n{self._day_text(plan, bold=True)}")
        self._feasibility(hid, plan)

    def _reject(self, hid: str, plan: dict, text: str) -> None:
        rejected = plan["rejections"]
        excluded = list({*plan["excluded"], *[p["recipe_ids"][0] for p in plan["proposals"]]})
        feedback = [*plan["feedback"], text]
        plan = repo.update_plan(self.db, hid, plan["id"], rejections=rejected + 1, feedback=feedback,
                                excluded=excluded)
        if rejected >= 2:
            self._say(hid, "🙏 I've tried twice and nothing else fits what's at home. Tell me the dish you want "
                           "and I'll order whatever is missing, or reply *yes* to go with option 1 above.")
            return
        self._replan(hid, plan["id"], "Sure, here's another take 👇")

    def cutoff(self, hid: str) -> None:
        """S3/S5 timeout. Silence never places an order."""
        plan = repo.latest_plan(self.db, hid)
        if not plan:
            return
        if plan["state"] == "review":
            if not plan["proposals"]:
                return self._say(hid, "⏰ No reply by the cutoff and I have no confirmed stock to plan from. "
                                      "Please update the kitchen so the cook has a menu.")
            if plan["stage"]:                                       # take option 1 for every meal still to choose
                meals = dict(plan["meals"])
                while plan["stage"]:
                    top1 = plan["proposals"][0]["recipe_ids"] if plan["proposals"] else []
                    meals[plan["stage"]] = top1
                    nxt = next((m for m in daystory.MEALS if m not in meals), None)
                    if not nxt:
                        break
                    plan = repo.update_plan(self.db, hid, plan["id"], meals=meals)
                    ctx = self._plan_ctx(hid, plan)
                    opts = self.planner.meal_options(nxt, ctx, self._stage_taken({**plan, "meals": meals}, nxt), lunch=meals.get("lunch", []))
                    plan = repo.update_plan(self.db, hid, plan["id"], proposals=[o.as_dict() for o in opts], stage=nxt)
                top = [d for m in ("lunch", "dinner", "breakfast") for d in meals.get(m, [])]
                if not top:
                    return self._say(hid, "⏰ No reply, and nothing I can plan from confirmed stock. Please update the kitchen.")
                plan = self._set_menu(hid, plan, list(dict.fromkeys(top)), meals, reviewed=False,
                                      notes=[*plan["notes"], "Owner did not review this menu."])
            else:
                top = plan["proposals"][0]["recipe_ids"]
                plan = self._set_menu(hid, plan, top, reviewed=False,
                                      notes=[*plan["notes"], "Owner did not review this menu."])
            repo.audit(self.db, hid, "cutoff_silent_pick", plan=plan["id"], dishes=top)
            self._say(hid, f"⏰ No reply. Going with *{_names(top)}* (unreviewed). No auto-order.")
            self._feasibility(hid, plan, hold=True)
        elif plan["state"] == "approval":
            repo.update_plan(self.db, hid, plan["id"], state="held")
            repo.audit(self.db, hid, "approval_timeout", plan=plan["id"])
            self._say(hid, "⏰ No approval. Order held. Reply *approve* anytime.")

    # ------------------------------------------------------------------ S4
    def _feasibility(self, hid: str, plan: dict, hold: bool = False) -> None:
        h = self._h(hid)
        needs = inv.needs_for(plan["chosen"], self._scale(plan))
        avail = inv.available(self.db, hid, h["sim_date"], plan["day"])
        gaps = inv.gaps(needs, avail, inv.list_items(self.db, hid))
        plan = repo.update_plan(self.db, hid, plan["id"], gaps=gaps)
        if not gaps:
            repo.update_plan(self.db, hid, plan["id"], state="ready", offer=None)
            repo.audit(self.db, hid, "feasible", plan=plan["id"])
            self._say(hid, f"✅ All in stock for *{_names(plan['chosen'])}*. Cook is briefed on arrival.")
            return
        lines = []
        for g in gaps:
            why = {"absent": "none in stock",
                   "partial": f"have {fmt_qty(g['have'], g['unit'])}, short",
                   "unconfirmed": "unconfirmed"}[g["reason"]]
            lines.append(f"• {g['name']} {fmt_qty(g['need'], g['unit'])} ({why})")
        self._say(hid, f"🔎 Short for *{_names(plan['chosen'])}*:\n" + "\n".join(lines) +
                       "\nIf it's there, tell me (*cream 100 ml*).")
        repo.audit(self.db, hid, "gaps_found", plan=plan["id"], gaps=gaps)
        self._gap_resolution(hid, plan["id"], hold=hold)

    # ------------------------------------------------------------------ S5
    def _collect_offers(self, h: dict, items: list[dict], minutes_left: int) -> list[dict]:
        offers = self.grocery.quote(items, h["pincode"])
        weight = int(sum(i["qty"] if i["unit"] != "pcs" else i["qty"] * 150 for i in items))
        svc = self.dispatch.check(h["pincode"], weight, minutes_left)
        if svc.serviceable:
            parcel = self.grocery.quote_parcel(items, h["pincode"], svc.eta_minutes)
            parcel["waybill"] = svc.waybill
            offers.append(parcel)
        else:
            repo.audit(self.db, h["id"], "dispatch_rerouted", reason=svc.reason, needed_within_min=minutes_left)
        for o in offers:
            o["overpriced"] = o["total"] > o["fair_total"] * h["price_ceiling_factor"] + 1e-6
        return offers

    def _gap_resolution(self, hid: str, plan_id: int, hold: bool = False, exclude_stores=()) -> None:
        h, plan = self._h(hid), repo.get_plan(self.db, hid, plan_id)
        items = [{"name": g["name"], "qty": g["short"], "unit": g["unit"]} for g in plan["gaps"]]
        minutes_left = self._minutes_left(h, plan)
        offers = [o for o in self._collect_offers(h, items, minutes_left) if o["store"] not in exclude_stores]
        viable = [o for o in offers if o["available"] and not o["overpriced"]]

        if not viable:
            return self._no_viable_offer(hid, plan, offers, hold)

        on_time = [o for o in viable if o["eta_minutes"] <= minutes_left]
        best = min(on_time, key=lambda o: (o["total"], o["eta_minutes"])) if on_time else \
            min(viable, key=lambda o: o["eta_minutes"])
        best["late"] = best["eta_minutes"] > minutes_left
        plan = repo.update_plan(self.db, hid, plan_id, offer=best)
        repo.audit(self.db, hid, "offer_selected", plan=plan_id, store=best["store"], total=best["total"],
                   eta=best["eta_minutes"], considered=[(o["store"], o["total"], o["eta_minutes"]) for o in offers])

        if not hold:
            ok, why = guards.auto_eligibility(h, plan, best)
            if ok:
                auth = guards.authorize_auto(h, plan, best)
                return self._place_order(hid, plan, best, auth)
            auto_note = f"\n(Not auto-ordering: {why}.)" if h["order_mode"] == "auto" else ""
        else:
            auto_note = ""

        lines = "\n".join(f"• {i['name']} {fmt_qty(i['qty'], i['unit'])}  ₹{i['price']:.0f}" for i in best["items"])
        late = ("\n⚠️ May arrive after the cook."
                if best["late"] else "")
        link = self.payment.payment_link(best["total"], "CookSmart groceries")
        new_state = "held" if hold else "approval"
        repo.update_plan(self.db, hid, plan_id, state=new_state)
        head = "🛒 Order on hold" if hold else "🛒 *Order*"
        self._say(hid, f"{head}: *{best['store']}* · ₹{best['total']:.0f} · ETA {best['eta_minutes']} min\n{lines}"
                       f"{late}{auto_note}\n💳 {link}\nReply *approve* or *no*.",
                  ["Approve order", "No, hold it"])

    def _no_viable_offer(self, hid: str, plan: dict, offers: list[dict], hold: bool) -> None:
        unavailable = sorted({m for o in offers for m in o["missing"]})
        if unavailable and all(not o["available"] for o in offers):
            problem = "out of stock everywhere: " + ", ".join(unavailable)
        elif offers and all(o["overpriced"] for o in offers if o["available"]):
            problem = "overpriced at every store right now"
        else:
            problem = "no store can supply all of it"
        repo.audit(self.db, hid, "no_viable_offer", plan=plan["id"], problem=problem)
        if hold:
            repo.update_plan(self.db, hid, plan["id"], state="held", offer=None)
            self._say(hid, f"😕 I couldn't find a good order for the missing items ({problem}). Nothing ordered, "
                           "nothing substituted. I'll look again before the cook arrives.")
            return
        repo.update_plan(self.db, hid, plan["id"], state="review", chosen=[], meals={}, reviewed=False, offer=None,
                         excluded=[*plan["excluded"], plan["chosen"][0]], stage="")
        self._begin_stage(hid, plan["id"], "breakfast",
                          f"😕 I can't get the missing items ({problem}). Nothing ordered or swapped. Let's choose again.")

    def _approve(self, hid: str, plan: dict) -> None:
        offer = plan["offer"]
        if not offer:
            return self._say(hid, "There's no order waiting for approval.")
        auth = guards.authorize_owner_tap(plan, offer)
        self._place_order(hid, plan, offer, auth)

    def _decline(self, hid: str, plan: dict) -> None:
        repo.update_plan(self.db, hid, plan["id"], state="held")
        repo.audit(self.db, hid, "order_declined", plan=plan["id"])
        self._say(hid, "👌 Okay, holding the order. Nothing was bought. I'll bring it up again tomorrow, "
                       "and the cook will be told what can be made from what's at home.")

    # ------------------------------------------------------------------ S6
    def _place_order(self, hid: str, plan: dict, offer: dict, auth) -> None:
        h = self._h(hid)
        guards.assert_can_charge(auth, offer["total"])
        res = self.payment.charge(offer["total"], h["mandate_ceiling"], fresh_tap=auth.kind == "owner_tap")
        if not res.ok:
            repo.create_order(self.db, hid, plan["id"], store=offer["store"], items=offer["items"],
                              total=offer["total"], status="payment_failed", eta_minutes=offer["eta_minutes"],
                              authorization=auth.kind)
            repo.update_plan(self.db, hid, plan["id"], state="approval")
            repo.audit(self.db, hid, "payment_failed", plan=plan["id"], reason=res.reason)
            return self._say(hid, f"❌ The payment didn't go through: {res.reason}. Nothing was ordered. "
                                  "Fix the payment method and reply *approve* to retry.",
                             ["Approve order", "No, hold it"])
        ref = self.grocery.place(offer)
        order = repo.create_order(self.db, hid, plan["id"], store=offer["store"], items=offer["items"],
                                  total=offer["total"], status="accepted", eta_minutes=offer["eta_minutes"],
                                  provider_ref=ref, waybill=offer.get("waybill"), payment_ref=res.ref,
                                  authorization=auth.kind)
        repo.update_plan(self.db, hid, plan["id"], state="ordered", order_id=order["id"])
        repo.audit(self.db, hid, "order_placed", plan=plan["id"], order=order["id"], auth=auth.kind,
                   total=offer["total"], store=offer["store"])
        repo.add_story(self.db, hid, plan["id"], "shop", f"Ordered from {offer['store']}",
                       [{"item": l["name"], "qty": l["qty"], "unit": l.get("unit", ""), "incoming": True} for l in offer["items"]])
        how = ("You approved it" if auth.kind == "owner_tap" else
               f"I ordered this automatically, within your ₹{min(h['auto_cap'], h['mandate_ceiling']):.0f} limit")
        late = "\n⚠️ May arrive after the cook." if offer.get("late") else ""
        self._say(hid, f"✅ *Ordered* from {offer['store']} · ₹{offer['total']:.0f} · ETA {offer['eta_minutes']} min.\n"
                       f"{how}. I'll recheck it before the cook arrives.{late}")

    def check_orders(self, hid: str) -> list[str]:
        """Re-verify accepted orders (cancellation after acceptance). Returns events."""
        events = []
        for o in repo.list_orders(self.db, hid):
            if o["status"] != "accepted":
                continue
            if self.grocery.status(o["provider_ref"]) == "cancelled":
                repo.update_order(self.db, hid, o["id"], status="cancelled")
                repo.audit(self.db, hid, "order_cancelled", order=o["id"], store=o["store"])
                events.append(f"order {o['id']} cancelled")
                plan = repo.get_plan(self.db, hid, o["plan_id"])
                self._say(hid, f"🚫 {o['store']} cancelled. Finding another shop.")
                repo.update_plan(self.db, hid, plan["id"], state="approval", order_id=None)
                self._gap_resolution(hid, plan["id"], exclude_stores={o["store"]})
        return events

    # ------------------------------------------------------------------ S7
    def _compose_brief(self, lang: str, dishes: list[str], start: list[str], wait: list[str], switched=False, meals=None):
        by_meal = cookmsgs.dish_names_by_meal(meals or {})
        names = by_meal or cookmsgs.dish_names(dishes)
        sfx = "_meals" if by_meal else ""
        if switched:
            msg = cookmsgs.render("switch" + sfx, lang, dishes=names)
        else:
            msg = cookmsgs.render("brief" + sfx, lang, dishes=names)
            if wait and start:
                msg = cookmsgs.concat(msg, cookmsgs.render("brief_wait", lang, wait=cookmsgs.dish_names(wait),
                                                           start=cookmsgs.dish_names(start)))
            elif wait:
                msg = cookmsgs.concat(msg, cookmsgs.render("brief_prep", lang))
        return cookmsgs.concat(msg, cookmsgs.render("brief_end", lang))

    def morning_handoff(self, hid: str) -> dict | None:
        plan = repo.latest_plan(self.db, hid)
        if not plan or plan["state"] == "closed":
            return None
        h = self._h(hid)
        if plan["state"] in ("review", "approval"):
            self.cutoff(hid)
            plan = repo.latest_plan(self.db, hid)
        repo.update_household(self.db, hid, sim_date=plan["day"])
        self.check_orders(hid)
        plan = repo.latest_plan(self.db, hid)
        lang = h["cook_language"]
        scale = self._scale(plan)

        if plan["flags"].get("cook_off") and plan["chosen"]:
            plan = repo.update_plan(self.db, hid, plan["id"], state="briefed",
                                    brief={"start": plan["chosen"], "wait": []})
            repo.audit(self.db, hid, "cook_off_day", plan=plan["id"])
            self._say(hid, f"🏖️ The cook is off today, so I didn't message her. Today's no-cook menu: "
                           f"*{_names(plan['chosen'])}*.")
            return plan

        stock = inv.available(self.db, hid, plan["day"], plan["day"])
        start, wait = self._split_by_stock(plan["chosen"], stock, scale)
        switched = False
        if not start and wait:
            # Nothing can start now and no delivery rescues it: fall back to a meal from what's at home.
            if plan["state"] != "ordered":
                props = self.planner.propose(self._plan_ctx(hid, plan, exclude=plan["chosen"]))
                alt = [p for p in props.items if p.feasible]
                if alt:
                    repo.audit(self.db, hid, "fallback_dish", plan=plan["id"], dishes=alt[0].recipe_ids)
                    self._say(hid, f"🔁 Groceries not coming. Switched to *{alt[0].name}* (from stock).")
                    plan = self._set_menu(hid, plan, alt[0].recipe_ids, alt[0].stock_meals or alt[0].meals)
                    start, wait, switched = plan["chosen"], [], True
        if not plan["chosen"] or (not start and not wait):
            self._cook_say(hid, cookmsgs.render("no_menu", lang))
            self._say(hid, "😟 The cook arrived but there is no menu I can stand behind. Please decide today's meal.")
            return plan
        repo.add_story(self.db, hid, plan["id"], "brief", "Cook briefed: " + _names(plan["chosen"]))
        if self._call_enabled(h) and self._place_call(hid, plan, "brief", start, wait):
            return repo.update_plan(self.db, hid, plan["id"], state="briefed", brief={"start": start, "wait": wait})
        self._cook_say(hid, self._compose_brief(lang, plan["chosen"], start, wait, switched, daystory.meals_of(plan)))
        plan = repo.update_plan(self.db, hid, plan["id"], state="briefed", brief={"start": start, "wait": wait})
        repo.audit(self.db, hid, "cook_briefed", plan=plan["id"], start=start, wait=wait)
        self._say(hid, f"👩‍🍳 Cook briefed: *{_names(plan['chosen'])}*." +
                       (f"\n⏳ Waiting on: {_names(wait)}." if wait else ""))
        return plan

    def _split_by_stock(self, dish_ids: list[str], stock: dict[str, dict], scale: float) -> tuple[list[str], list[str]]:
        left = {k: v["qty"] for k, v in stock.items()}
        start, wait = [], []
        for rid in dish_ids:
            needs = inv.needs_for([rid], scale)
            if all(left.get(i, 0) + 1e-9 >= n["qty"] for i, n in needs.items()):
                for i, n in needs.items():
                    left[i] -= n["qty"]
                start.append(rid)
            else:
                wait.append(rid)
        return start, wait

    # ------------------------------------------------------------------ delivery + door handshake
    def rider_arrives(self, hid: str, voice_sample: str) -> dict:
        h = self._h(hid)
        order = next((o for o in reversed(repo.list_orders(self.db, hid)) if o["status"] == "accepted"), None)
        if not order:
            self._say(hid, "🚪 A rider is at the door but there's no open order. Not handing anything over.")
            return {"released": False, "reason": "no open order"}
        if self.grocery.status(order["provider_ref"]) == "cancelled":
            self.check_orders(hid)
            return {"released": False, "reason": "order was cancelled"}
        if self.voice.verify(bool(h["cook_voice_enrolled"]), voice_sample):
            repo.audit(self.db, hid, "handshake_voice_ok", order=order["id"])
            self._deliver(hid, order)
            return {"released": True, "via": "voice"}
        otp = f"{random.randint(1000, 9999)}"
        repo.update_order(self.db, hid, order["id"], otp=otp)
        repo.audit(self.db, hid, "handshake_voice_failed", order=order["id"], sample=voice_sample)
        self._say(hid, f"🚪 A rider is at the door but the voice check didn't match the cook (heard: {voice_sample}). "
                       f"I'm not handing over the groceries.\n🔐 OTP sent to you: *{otp}*. "
                       "Share it only if this is your delivery.")
        return {"released": False, "otp_required": True}

    def door_otp(self, hid: str, code: str) -> dict:
        order = next((o for o in reversed(repo.list_orders(self.db, hid)) if o["status"] == "accepted"), None)
        if not order or not order["otp"]:
            return {"released": False, "reason": "no OTP pending"}
        if code.strip() != order["otp"]:
            repo.audit(self.db, hid, "handshake_otp_wrong", order=order["id"])
            self._say(hid, "🚫 Wrong OTP entered at the door. Still not handing over.")
            return {"released": False, "reason": "wrong OTP"}
        repo.audit(self.db, hid, "handshake_otp_ok", order=order["id"])
        self._deliver(hid, order)
        return {"released": True, "via": "otp"}

    def _deliver(self, hid: str, order: dict) -> None:
        h = self._h(hid)
        for line in order["items"]:
            inv.add_stock(self.db, hid, line["name"], line["qty"], h["sim_date"])
        repo.update_order(self.db, hid, order["id"], status="delivered", otp=None)
        repo.add_story(self.db, hid, order["plan_id"], "delivery", f"Groceries from {order['store']} arrived",
                       [{"item": l["name"], "qty": l["qty"], "unit": l.get("unit", "")} for l in order["items"]])
        if hasattr(self.grocery, "mark_delivered"):
            self.grocery.mark_delivered(order["provider_ref"])
        plan = repo.get_plan(self.db, hid, order["plan_id"])
        self._say(hid, f"📦 Delivered from {order['store']}. Stock updated.")
        if plan["state"] == "briefed" and plan["brief"] and plan["brief"]["wait"]:
            wait = plan["brief"]["wait"]
            self._cook_say(hid, cookmsgs.render("delivered", h["cook_language"], wait=cookmsgs.dish_names(wait)))
            repo.update_plan(self.db, hid, plan["id"], brief={"start": plan["chosen"], "wait": []})
        elif plan["state"] == "ordered":
            repo.update_plan(self.db, hid, plan["id"], state="ready")

    # ------------------------------------------------------------------ cook chat
    def handle_cook(self, hid: str, text: str, voice: bool = True) -> None:
        """Typed text from the cook (optionally flagged as a voice note in the simulator)."""
        lang = self._h(hid)["cook_language"]
        tr = self.speech.transcribe(text, lang) if voice else Transcript(text, 1.0, lang, "text")
        self._cook_turn(hid, tr, shown=text, voice=voice)

    def handle_cook_audio(self, hid: str, audio: bytes, mime: str = "audio/wav", hint: str | None = None) -> None:
        """A real recorded voice note: transcribed by the speech provider, then handled like any message."""
        lang = self._h(hid)["cook_language"]
        tr = self.speech.transcribe_audio(audio, mime, lang, hint)
        repo.audit(self.db, hid, "stt", source=tr.source, confidence=round(tr.confidence, 2), chars=len(tr.text),
                   audio_bytes=len(audio), error=tr.error, raw=tr.raw)
        self._cook_turn(hid, tr, shown=tr.text or "(unclear audio)", voice=True)

    def _cook_turn(self, hid: str, tr: Transcript, shown: str, voice: bool) -> None:
        h = self._h(hid)
        lang = h["cook_language"]
        plan = repo.latest_plan(self.db, hid)
        repo.add_message(self.db, hid, "cook", "user", shown,
                         {"voice": True, "stt": tr.source, "confidence": round(tr.confidence, 2)} if voice else None)
        if tr.confidence < LOW_CONFIDENCE or not tr.text.strip():
            repo.audit(self.db, hid, "cook_low_confidence", confidence=tr.confidence, source=tr.source)
            return self._cook_say(hid, cookmsgs.render("ask_repeat", lang))

        intents = self.nlu.cook(tr.text, plan["pending"] if plan else None)
        kinds = [i["type"] for i in intents]
        if kinds == ["yes"]:
            if plan and plan["pending"]:
                return self._apply_cook_intents(hid, plan, plan["pending"])
            if plan and plan["state"] == "briefed":
                repo.audit(self.db, hid, "cook_ack", plan=plan["id"])
                self._say(hid, "👍 The cook confirmed today's menu.")
            return self._cook_say(hid, cookmsgs.render("thanks", lang))
        if kinds == ["no"]:
            if plan and plan["pending"]:
                repo.update_plan(self.db, hid, plan["id"], pending=None)
                return self._cook_say(hid, cookmsgs.render("retry", lang))
            if plan and plan["state"] == "briefed":      # "samajh gaye?" -> "nahi": say it again
                return self._cook_arrived(hid, plan, lang)
            return self._cook_say(hid, cookmsgs.render("retry", lang))

        real = [i for i in intents if i["type"] in PROBLEMS]
        if real and plan:
            # Read back before acting: never act on words the cook didn't confirm.
            repo.update_plan(self.db, hid, plan["id"], pending=real)
            repo.audit(self.db, hid, "cook_readback", intents=real, transcript=tr.text)
            return self._cook_say(hid, cookmsgs.render("readback", lang, summary=cookmsgs.summarize_intents(real)))
        if real:
            return self._cook_say(hid, cookmsgs.render("no_menu", lang))
        if "leave" in kinds:
            return self._cook_leave(hid, lang)
        if "done" in kinds:
            return self._cook_done(hid, plan, lang)
        if "arrived" in kinds or "ask_menu" in kinds:
            return self._cook_arrived(hid, plan, lang)
        if "greeting" in kinds:
            if plan and plan["state"] == "briefed":
                return self._cook_arrived(hid, plan, lang)
            return self._cook_say(hid, cookmsgs.render("greet", lang))
        repo.audit(self.db, hid, "cook_not_understood", text=tr.text)
        self._say(hid, f"❓ The cook said something I couldn't understand: “{tr.text}”. I asked her to rephrase.")
        self._cook_say(hid, cookmsgs.render("help", lang))

    def _cook_arrived(self, hid: str, plan: dict | None, lang: str) -> None:
        if not plan or plan["state"] == "closed":
            return self._cook_say(hid, cookmsgs.render("no_menu", lang))
        if plan["state"] == "briefed":
            b = plan["brief"] or {"start": plan["chosen"], "wait": []}
            return self._cook_say(hid, self._compose_brief(lang, plan["chosen"], b["start"], b["wait"], meals=daystory.meals_of(plan)))
        if plan["state"] == "closing":
            return self._cook_say(hid, cookmsgs.render("eod", lang))
        self.morning_handoff(hid)

    def _cook_done(self, hid: str, plan: dict | None, lang: str) -> None:
        if plan and plan["state"] in ("briefed", "ready", "ordered"):
            return self.end_of_day(hid)
        self._cook_say(hid, cookmsgs.render("great", lang))

    def _cook_leave(self, hid: str, lang: str) -> None:
        repo.audit(self.db, hid, "cook_leave")
        self._cook_say(hid, cookmsgs.render("leave_ok", lang))
        self._say(hid, "🏖️ The cook says she can't come tomorrow.")
        self._owner_flags(hid, {"cook_off": True})

    def _apply_cook_intents(self, hid: str, plan: dict, intents: list[dict], notify_cook: bool = True) -> None:
        h = self._h(hid)
        day = h["sim_date"]
        report = dict(plan["report"])
        said, problem, changed = [], None, False
        for i in intents:
            t = i["type"]
            if t == "used_up":
                inv.set_qty(self.db, hid, i["item"], 0, day)
                report[i["item"]] = 0
                said.append(f"{i['item']} finished")
                changed = True
            elif t == "spoiled":
                inv.set_qty(self.db, hid, i["item"], 0, day)
                report[i["item"]] = 0
                repo.audit(self.db, hid, "item_spoiled", item=i["item"])
                said.append(f"{i['item']} spoiled 🗑️")
                changed = True
            elif t == "remaining":
                inv.set_qty(self.db, hid, i["item"], i["qty"], day)
                report[i["item"]] = i["qty"]
                said.append(f"{i['item']} left: {fmt_qty(i['qty'], i['unit'])}")
                changed = True
            elif t == "low":
                inv.mark_uncertain(self.db, hid, i["item"])
                said.append(f"{i['item']} running low (needs a check)")
            elif t == "cannot_cook":
                problem = i.get("reason", "other")
                said.append({"stove": "stove/gas is not working", "cooker": "pressure cooker is not working",
                             "time": "short on time"}.get(problem, "cannot cook"))
        plan = repo.update_plan(self.db, hid, plan["id"], pending=None, report=report)
        repo.audit(self.db, hid, "cook_update_applied", intents=intents)
        if notify_cook:
            self._cook_say(hid, cookmsgs.render("noted", h["cook_language"]))
        self._say(hid, "👩‍🍳 *Cook update:* " + "; ".join(said) + ".")
        if plan["state"] == "closing":
            return
        if problem:
            if self._problem_applies(plan, problem):      # the live call action may already have switched the dish
                return self._switch_dish(hid, plan, problem)
            return

        if changed and plan["state"] == "briefed":
            avail = inv.available(self.db, hid, h["sim_date"], plan["day"])
            if inv.gaps(inv.needs_for(plan["chosen"], self._scale(plan)), avail):
                self._switch_dish(hid, plan, "ingredient")

    def _switch_dish(self, hid: str, plan: dict, reason: str) -> None:
        h = self._h(hid)
        constraint = {"stove": "stove_broken", "cooker": "cooker_broken", "time": "time_short"}.get(reason)
        repo.add_memory(self.db, hid, "constraint", f"{reason} problem on {h['sim_date']}", h["sim_date"])
        if reason == "time":
            for rid in plan["chosen"]:
                if RECIPES[rid]["prep"] > 25:
                    repo.add_memory(self.db, hid, "avoid_dish", rid, h["sim_date"])
        ctx = self._plan_ctx(hid, plan, constraints=[constraint] if constraint else [], exclude=plan["chosen"])
        feasible = [p for p in self.planner.propose(ctx).items if p.feasible]
        lang = h["cook_language"]
        if not feasible:
            repo.audit(self.db, hid, "switch_failed", reason=reason)
            self._cook_say(hid, cookmsgs.render("no_menu", lang))
            return self._say(hid, f"😟 The cook can't make today's meal ({reason}) and nothing at home fits. "
                                  "Please decide: order in, or tell me a dish.")
        plan = self._set_menu(hid, plan, feasible[0].recipe_ids, feasible[0].stock_meals or feasible[0].meals)
        new = plan["chosen"]
        repo.update_plan(self.db, hid, plan["id"], brief={"start": new, "wait": []})
        repo.audit(self.db, hid, "dish_switched", reason=reason, to=new)
        self._cook_say(hid, cookmsgs.render("switch", lang, dishes=cookmsgs.dish_names(new)))
        self._say(hid, f"🔁 {reason} problem. Switched to *{_names(new)}*.")

    # ------------------------------------------------------------------ S8
    def end_of_day(self, hid: str) -> None:
        plan = repo.latest_plan(self.db, hid)
        if not plan or plan["state"] not in ("briefed", "ready", "ordered"):
            return
        repo.update_plan(self.db, hid, plan["id"], state="closing")
        h = self._h(hid)
        if self._call_enabled(h) and self._place_call(hid, plan, "reconcile", plan["chosen"], []):
            return
        self._cook_say(hid, cookmsgs.render("eod", h["cook_language"]))
        self._say(hid, "🌙 Asked the cook what was used.")

    def serve_meal(self, hid: str, meal: str) -> dict | None:
        """A meal is served: record it and what it used. Stock is reconciled once, at close of day."""
        plan = repo.latest_plan(self.db, hid)
        if meal not in daystory.MEALS or not plan or plan["state"] not in ("briefed", "closing") or meal in plan["served"]:
            return plan
        ids = daystory.meals_of(plan)[meal]
        needs = daystory.meal_needs(plan, self._scale(plan), meal)
        plan = repo.update_plan(self.db, hid, plan["id"], served=plan["served"] + [meal])
        text = (_names(ids) if ids else {"breakfast": "Light: chai and toast", "lunch": "Nothing planned",
                                          "dinner": "Nothing planned"}[meal])
        repo.add_story(self.db, hid, plan["id"], meal, text, daystory.deltas_from(needs))
        repo.audit(self.db, hid, "meal_served", plan=plan["id"], meal=meal, dishes=ids)
        return plan

    def close_day(self, hid: str) -> dict | None:
        plan = repo.latest_plan(self.db, hid)
        if not plan or plan["state"] == "closed":
            return plan
        h = self._h(hid)
        day = plan["day"]
        if h["sim_date"] < day:
            repo.update_household(self.db, hid, sim_date=day)
        reported = set(plan["report"])
        before = {i["name"]: i["qty"] for i in inv.list_items(self.db, hid)}
        estimated = inv.apply_usage(self.db, hid, inv.needs_for(plan["chosen"], self._scale(plan)), day, reported)
        for rid in plan["chosen"]:
            repo.add_meal(self.db, hid, day, rid, RECIPES[rid]["name"], plan["reviewed"])
        plan = repo.update_plan(self.db, hid, plan["id"], state="closed")
        after = {i["name"]: i["qty"] for i in inv.list_items(self.db, hid)}
        repo.add_story(self.db, hid, plan["id"], "wrapup", "Stock reconciled with what the cook reported", [
            {"item": k, "qty": round(after.get(k, 0) - v, 1), "unit": ITEMS[k]["unit"]} for k, v in before.items()
            if k in ITEMS and abs(after.get(k, 0) - v) > 0.01])
        repo.audit(self.db, hid, "day_closed", plan=plan["id"], reported=sorted(reported), estimated=estimated)
        msg = f"🌙 *Day closed.* Cooked: {_names(plan['chosen'])}."
        if reported:
            msg += f"\nCook reported: {', '.join(sorted(reported))}."
        if estimated:
            msg += "\nEstimated (cook didn't report; recheck): " + ", ".join(estimated) + "."
        self._say(hid, msg)
        return plan

    # ------------------------------------------------------------------ Gnani voice agent: phone calls to the cook
    def _call_enabled(self, h: dict) -> bool:
        return self.caller is not None and h["preferences"].get("cook_channel") == "call"

    def _call_brief(self, hid: str, plan: dict, call_type: str, start, wait) -> cookbrief.CookBriefData:
        h = self._h(hid)
        return cookbrief.build(self.db, hid, h, plan, call_type=call_type, start=start, wait=wait,
                               order_coming=plan["state"] == "ordered")

    def _place_call(self, hid: str, plan: dict, call_type: str, start, wait) -> bool:
        """Phone the cook. Returns False (and the caller falls back to a chat message) if it can't be placed,
        so she is never left waiting."""
        h = self._h(hid)
        live = bool(self.caller.describe().get("live"))
        phone = h["cook_phone"] or (None if live else "+91-demo")
        if not phone:
            self._say(hid, "📵 I can't phone the cook: her number isn't saved. I'll message her instead.")
            return False
        brief = self._call_brief(hid, plan, call_type, start, wait)
        row = repo.add_call(self.db, hid, plan["id"], call_type)
        try:
            self.caller.start_call(CallRequest(hid, row["reference_id"], call_type, phone, cookbrief.to_variables(brief)))
        except Exception as e:
            repo.update_call(self.db, row["reference_id"], status="failed", payload={"error": str(e)[:300]})
            repo.audit(self.db, hid, "call_failed", error=str(e)[:300], call=row["reference_id"])
            self._say(hid, f"📵 I couldn't place the call ({str(e)[:120]}). Messaging the cook instead so she isn't left waiting.")
            return False
        repo.audit(self.db, hid, "call_placed", call=row["reference_id"], type=call_type)
        what = "today's brief" if call_type == "brief" else "an end-of-day check on what was used"
        self._say(hid, f"📞 *Calling the cook* with {what}.\n" + (cookbrief.spoken_summary(brief) if call_type == "brief" else ""))
        return True

    def _chat_brief(self, hid: str, plan: dict) -> None:
        lang = self._h(hid)["cook_language"]
        b = plan["brief"] or {"start": plan["chosen"], "wait": []}
        self._cook_say(hid, self._compose_brief(lang, plan["chosen"], b["start"], b["wait"], meals=daystory.meals_of(plan)))

    def _problem_applies(self, plan: dict, reason: str) -> bool:
        """Is the reported problem still a problem for the chosen dishes? (False once a switch already happened.)"""
        rs = [RECIPES[r] for r in plan["chosen"]]
        return {"stove": any(r["stove"] for r in rs), "cooker": any("cooker" in r["tools"] for r in rs),
                "time": any(r["prep"] > 30 for r in rs)}.get(reason, True)

    def handle_call_result(self, payload: dict) -> dict:
        """Post-call webhook from the Gnani agent. Idempotent on conversation_id. Only what the cook CONFIRMED
        on the call is applied; the rest is shown to the owner and left alone."""
        oc = callresult.parse_webhook(payload)
        row = repo.find_call(self.db, reference_id=oc.reference_id, conversation_id=oc.conversation_id)
        if not row:
            return {"ok": False, "ignored": "unknown call"}
        if row["status"] == "processed":
            return {"ok": True, "duplicate": True}
        hid = row["household_id"]
        repo.update_call(self.db, row["reference_id"], status="processed", conversation_id=oc.conversation_id,
                         disposition=oc.disposition, payload={k: v for k, v in payload.items() if k != "transcript"})
        plan = repo.get_plan(self.db, hid, row["plan_id"]) or repo.latest_plan(self.db, hid)
        repo.audit(self.db, hid, "call_result", call=row["reference_id"], disposition=oc.disposition,
                   ignored=oc.ignored)
        def alert() -> None:                 # last message in the chat, so it can't be buried under routine updates
            if oc.safety_issue:
                self._say(hid, "🚨 *The cook reported a safety issue on the call* "
                               f"({oc.notes or 'no details'}). Please call her right now.")

        if oc.no_answer:
            self._say(hid, "📵 The cook didn't pick up the call. I've sent her the brief as a voice note instead.")
            if row["call_type"] == "brief":
                self._chat_brief(hid, plan)
            alert()
            return {"ok": True, "fallback": "chat"}

        confirmed, unconfirmed = callresult.to_intents(oc)
        if oc.acknowledged and row["call_type"] == "brief" and not oc.safety_issue:
            self._say(hid, "👍 The cook confirmed today's menu on the call.")
        if unconfirmed:
            self._say(hid, "⚠️ Not applied (she didn't confirm): " +
                      "; ".join(f"{i.get('item') or i.get('reason')} ({i['type']})" for i in unconfirmed) +
                      ". I'll leave stock as it is until it's confirmed.")
        if confirmed:
            self._apply_cook_intents(hid, plan, confirmed, notify_cook=False)
        if oc.leave_tomorrow:
            self._owner_flags(hid, {"cook_off": True})
        if row["call_type"] == "reconcile":
            self.close_day(hid)
        alert()
        return {"ok": True, "applied": len(confirmed), "not_applied": len(unconfirmed)}

    def live_cook_problem(self, hid: str, reason: str, item: str | None = None) -> str:
        """On-call action: the cook confirmed a problem on the phone; switch today's dish and return what the
        agent should say next (in Hindi)."""
        plan = repo.latest_plan(self.db, hid)
        if not plan or plan["state"] not in ("briefed", "ready", "ordered") or not plan["chosen"]:
            return "मैं मैडम/सर से पूछकर बताती हूँ।"
        if reason not in ("stove", "cooker", "time", "ingredient"):
            return "मैं मैडम/सर से पूछकर बताती हूँ।"
        before = list(plan["chosen"])
        if reason == "ingredient" and item in ITEMS:
            inv.set_qty(self.db, hid, item, 0, self._h(hid)["sim_date"])
            repo.audit(self.db, hid, "live_ingredient_gone", item=item)
        self._switch_dish(hid, plan, reason)
        plan = repo.latest_plan(self.db, hid)
        if plan["chosen"] == before:
            return "आज के लिए कोई दूसरा विकल्प नहीं मिला। मैं मैडम/सर को बता देती हूँ।"
        return f"ठीक है, आज {cookmsgs.dish_names(plan['chosen'])} बनाइए।"

    def dynamic_brief(self, hid: str) -> dict:
        """Dynamic-message endpoint (Gnani calls us, 10 s timeout): always the freshest brief, never stale."""
        plan = repo.latest_plan(self.db, hid)
        if not plan or not plan["chosen"]:
            return {"text": "आज का मेन्यू अभी तय नहीं है। मैं मैडम/सर से पूछकर बताती हूँ।", "user_context": {}}
        b = plan["brief"] or {"start": plan["chosen"], "wait": []}
        brief = self._call_brief(hid, plan, "brief", b["start"], b["wait"])
        return {"text": cookbrief.spoken_summary(brief), "user_context": cookbrief.to_variables(brief)}

    # ------------------------------------------------------------------ settings
    def set_settings(self, hid: str, order_mode: str | None = None, auto_cap: int | None = None) -> None:
        changes = {}
        if order_mode in ("approve", "auto"):
            changes["order_mode"] = order_mode
        if auto_cap is not None and auto_cap >= 0:
            changes["auto_cap"] = int(auto_cap)
        if not changes:
            return
        repo.update_household(self.db, hid, **changes)
        repo.audit(self.db, hid, "settings_changed", **changes)
        h = self._h(hid)
        if h["order_mode"] == "auto":
            self._say(hid, f"⚙️ Ordering mode: *AUTO*. I'll order missing items myself up to ₹{h['auto_cap']} per order "
                           "once you've accepted a menu. Anything bigger, or any menu you haven't reviewed, "
                           "still needs your approval.")
        else:
            self._say(hid, "⚙️ Ordering mode: *APPROVE EACH ORDER*. I'll never buy without your tap.")
