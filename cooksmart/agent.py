"""The CookSmart agent: the S1-S8 state machine.

Claude (via Planner/NLU) proposes and understands; everything that has consequences (stock, money,
what the cook is told) is decided here, in code, behind guards.

Plan states:  review -> (approval | held) -> ordered -> ready -> briefed -> closing -> closed
"""
from __future__ import annotations

import datetime as dt
import random

from . import cookmsgs, guards, repo
from . import inventory as inv
from .channels import MessageChannel
from .db import DB
from .nlu import NLU
from .planner import PlanContext, Planner
from .providers.dispatch import DispatchProvider
from .providers.grocery import GroceryProvider
from .providers.payment import PaymentProvider
from .providers.speech import LOW_CONFIDENCE, SpeechProvider, Transcript
from .providers.voice import VoiceVerifier
from .recipes import ITEMS, RECIPES, fmt_qty

NIGHT_MINUTES_LEFT = 630     # ~21:30 order -> 08:00 cook arrival
MORNING_MINUTES_LEFT = 30
PROBLEMS = ("used_up", "remaining", "low", "spoiled", "cannot_cook")

HELP = (
    "👋 *I'm CookSmart.* Here's what you can tell me:\n"
    "• *1*, *1 and 2*, *palak paneer*: choose tomorrow's menu\n"
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


def _flat(proposals: list[dict], picks: list[int]) -> list[str]:
    out: list[str] = []
    for n in picks:
        if 1 <= n <= len(proposals):
            out += [i for i in proposals[n - 1]["recipe_ids"] if i not in out]
    return out


class Agent:
    def __init__(self, db: DB, channel: MessageChannel, planner: Planner, nlu: NLU, speech: SpeechProvider,
                 grocery: GroceryProvider, dispatch: DispatchProvider, payment: PaymentProvider,
                 voice: VoiceVerifier):
        self.db, self.channel, self.planner, self.nlu = db, channel, planner, nlu
        self.speech, self.grocery, self.dispatch = speech, grocery, dispatch
        self.payment, self.voice = payment, voice

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
            exclude_ids=set(exclude or []))

    def _plan_ctx(self, hid: str, plan: dict, **kw) -> PlanContext:
        return self._ctx(hid, plan["day"], flags=plan["flags"], **kw)

    def _minutes_left(self, h: dict, plan: dict) -> int:
        return NIGHT_MINUTES_LEFT if h["sim_date"] < plan["day"] else MORNING_MINUTES_LEFT

    def _upcoming(self, h: dict, plan: dict | None) -> bool:
        return bool(plan) and plan["state"] != "closed" and plan["day"] > h["sim_date"]

    def _fmt_props(self, props: list[dict]) -> str:
        lines = []
        for n, p in enumerate(props, 1):
            lines.append(f"*{n}. {p['name']}*\n   {p['reason']}")
            if not p["feasible"]:
                lines.append("   🛒 To buy: " + ", ".join(g["name"] for g in p["gaps"]))
        return "\n".join(lines)

    def _send_proposals(self, hid: str, plan: dict, preface: str = "") -> None:
        props = plan["proposals"]
        head = (preface + "\n\n") if preface else ""
        if not props:
            self._say(hid, head + "🤷 I can't build a menu from stock I've confirmed. Please update the kitchen "
                                  "(e.g. *tomato 4*, *paneer 200 g*) or say *all good* if it's all still there.")
            return
        text = head + "🍽️ *Tomorrow's options*\n" + self._fmt_props(props)
        if plan["notes"]:
            text += "\n\n📝 " + " ".join(plan["notes"])
        text += "\n\nReply with a number (or *1 and 2*), or tell me what you'd like instead."
        buttons = [f"Accept {n}" for n in range(1, len(props) + 1)] + ["Something else"]
        self._say(hid, text, buttons)

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
        preface += self._flag_lines(flags, h)
        spoiled = inv.spoiled_items(self.db, hid, day)
        if spoiled:
            preface.append("🗑️ *Past use-by for tomorrow* (please check and discard): " +
                           ", ".join(i["name"] for i in spoiled) + ".")
        doubtful = inv.doubtful_items(self.db, hid, today, day)
        if doubtful:
            preface.append("🤔 I'm not sure about these, so I won't plan around them: " +
                           ", ".join(f"{i['name']} ({fmt_qty(i['qty'], i['unit'])})" for i in doubtful) +
                           ". Did you use them? Reply *all good* or tell me what changed.")

        props = self.planner.propose(self._ctx(hid, day, flags=flags))
        plan = repo.update_plan(self.db, hid, plan["id"], proposals=[p.as_dict() for p in props.items],
                                notes=props.tradeoffs, state="review")
        repo.audit(self.db, hid, "nightly_review", plan=plan["id"], source=props.source, flags=flags,
                   proposals=[p.recipe_ids for p in props.items], doubtful=[i["name"] for i in doubtful])
        self._send_proposals(hid, plan, "\n".join(preface))
        return plan

    def _replan(self, hid: str, plan_id: int, preface: str = "") -> None:
        plan = repo.get_plan(self.db, hid, plan_id)
        props = self.planner.propose(self._plan_ctx(hid, plan, feedback=plan["feedback"], exclude=plan["excluded"]))
        plan = repo.update_plan(self.db, hid, plan_id, proposals=[p.as_dict() for p in props.items],
                                notes=props.tradeoffs)
        repo.audit(self.db, hid, "replanned", plan=plan_id, source=props.source)
        self._send_proposals(hid, plan, preface)

    # ------------------------------------------------------------------ owner chat
    def handle_owner(self, hid: str, text: str) -> None:
        h = self._h(hid)
        repo.add_message(self.db, hid, "owner", "user", text)
        a = self.nlu.owner(text)
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
        if act == "redo":
            return self._redo(hid)
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
        if act == "dish_request" and state in ("review", "approval", "held", "ready"):
            return self._choose(hid, plan, a["dishes"], reviewed=True)
        if act == "choose" and state == "review":
            ids = _flat(plan["proposals"], a["choices"])
            if ids:
                return self._choose(hid, plan, ids, reviewed=True)
        if act == "yes" and state == "review" and plan["proposals"]:
            return self._choose(hid, plan, plan["proposals"][0]["recipe_ids"], reviewed=True)
        if act == "yes" and state in ("approval", "held"):
            return self._approve(hid, plan)
        if act == "no" and state in ("approval", "held"):
            return self._decline(hid, plan)
        if act in ("no", "other") and state == "review":
            return self._reject(hid, plan, a.get("text", text))
        if act == "other":
            return self._say(hid, "🙂 I didn't catch that. Type *help* to see what I understand.")
        self._say(hid, f"👍 Noted. (Current status: {state}.) I'll keep you posted.")

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
        repo.update_plan(self.db, hid, plan["id"], state="review", chosen=[], offer=None, gaps=[], reviewed=False,
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
    def _choose(self, hid: str, plan: dict, ids: list[str], reviewed: bool) -> None:
        plan = repo.update_plan(self.db, hid, plan["id"], chosen=ids, reviewed=reviewed, offer=None)
        repo.audit(self.db, hid, "menu_chosen", plan=plan["id"], dishes=ids, reviewed=reviewed)
        self._say(hid, f"👍 Got it: *{_names(ids)}*. Checking the kitchen...")
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
            top = plan["proposals"][0]["recipe_ids"]
            plan = repo.update_plan(self.db, hid, plan["id"], chosen=top, reviewed=False,
                                    notes=[*plan["notes"], "Owner did not review this menu."])
            repo.audit(self.db, hid, "cutoff_silent_pick", plan=plan["id"], dishes=top)
            self._say(hid, f"⏰ No reply by the cutoff, so I'm going with *{_names(top)}* and noting that "
                           "you didn't review it. I won't order anything on my own for this.")
            self._feasibility(hid, plan, hold=True)
        elif plan["state"] == "approval":
            repo.update_plan(self.db, hid, plan["id"], state="held")
            repo.audit(self.db, hid, "approval_timeout", plan=plan["id"])
            self._say(hid, "⏰ No approval before the cutoff, so I'm holding the grocery order. "
                           "Reply *approve* any time to place it; I'll remind you tomorrow too.")

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
            self._say(hid, f"✅ Everything for *{_names(plan['chosen'])}* is in the kitchen. "
                           "Feel free to double-check; if something's off, tell me before morning. "
                           "I'll brief the cook when she arrives.")
            return
        lines = []
        for g in gaps:
            why = {"absent": "none in stock",
                   "partial": f"have {fmt_qty(g['have'], g['unit'])}, not enough, so I treat it as missing",
                   "unconfirmed": "not confirmed, so I can't rely on it"}[g["reason"]]
            lines.append(f"• {g['name']} {fmt_qty(g['need'], g['unit'])} ({why})")
        self._say(hid, f"🔎 For *{_names(plan['chosen'])}* I'm missing:\n" + "\n".join(lines) +
                       "\nPlease look in the kitchen. If it's actually there, tell me (e.g. *cream 100 ml*).")
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
        late = ("\n⚠️ This may arrive after the cook; I'll tell her what to start with."
                if best["late"] else "")
        link = self.payment.payment_link(best["total"], "CookSmart groceries")
        new_state = "held" if hold else "approval"
        repo.update_plan(self.db, hid, plan_id, state=new_state)
        head = "🛒 I'm holding this order for your approval" if hold else "🛒 *Recommended order*"
        self._say(hid, f"{head}: *{best['store']}* · ₹{best['total']:.0f} · ETA {best['eta_minutes']} min\n{lines}"
                       f"{late}{auto_note}\n\n💳 {link}\nReply *approve* to order, or *no* to hold.",
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
        props = self.planner.propose(self._plan_ctx(hid, plan, exclude=[*plan["excluded"], plan["chosen"][0]]))
        feasible = [p for p in props.items if p.feasible]
        repo.update_plan(self.db, hid, plan["id"], state="review", chosen=[], reviewed=False, offer=None,
                         proposals=[p.as_dict() for p in feasible])
        plan = repo.get_plan(self.db, hid, plan["id"])
        msg = f"😕 I can't get the missing items ({problem}). I haven't ordered or swapped anything."
        if feasible:
            self._send_proposals(hid, plan, msg + " Instead, you could make this from what's at home:")
        else:
            self._say(hid, msg + " I also can't find a meal that works with current stock; please advise.")

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
        how = ("You approved it" if auth.kind == "owner_tap" else
               f"I ordered this automatically, within your ₹{min(h['auto_cap'], h['mandate_ceiling']):.0f} limit")
        late = "\n⚠️ It may arrive after the cook; she'll be told what to start with." if offer.get("late") else ""
        self._say(hid, f"✅ *Order placed* with {offer['store']}: ₹{offer['total']:.0f}, ETA {offer['eta_minutes']} min.\n"
                       f"{how}. An accepted order isn't a delivery, so I'll re-check it before the cook "
                       f"arrives.{late}")

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
                self._say(hid, f"🚫 {o['store']} cancelled your order after accepting it. Looking for another option...")
                repo.update_plan(self.db, hid, plan["id"], state="approval", order_id=None)
                self._gap_resolution(hid, plan["id"], exclude_stores={o["store"]})
        return events

    # ------------------------------------------------------------------ S7
    def _compose_brief(self, lang: str, dishes: list[str], start: list[str], wait: list[str], switched=False):
        if switched:
            msg = cookmsgs.render("switch", lang, dishes=cookmsgs.dish_names(dishes))
        else:
            msg = cookmsgs.render("brief", lang, dishes=cookmsgs.dish_names(dishes))
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
                    self._say(hid, f"🔁 The groceries aren't coming, so I switched today's menu to "
                                   f"*{alt[0].name}* (made from stock). Nothing was ordered or swapped silently.")
                    plan = repo.update_plan(self.db, hid, plan["id"], chosen=alt[0].recipe_ids)
                    start, wait, switched = alt[0].recipe_ids, [], True
        if not plan["chosen"] or (not start and not wait):
            self._cook_say(hid, cookmsgs.render("no_menu", lang))
            self._say(hid, "😟 The cook arrived but there is no menu I can stand behind. Please decide today's meal.")
            return plan
        self._cook_say(hid, self._compose_brief(lang, plan["chosen"], start, wait, switched))
        plan = repo.update_plan(self.db, hid, plan["id"], state="briefed", brief={"start": start, "wait": wait})
        repo.audit(self.db, hid, "cook_briefed", plan=plan["id"], start=start, wait=wait)
        self._say(hid, f"👩‍🍳 The cook has been briefed on: *{_names(plan['chosen'])}*." +
                       (f"\n⏳ Waiting on groceries for: {_names(wait)}." if wait else ""))
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
        if hasattr(self.grocery, "mark_delivered"):
            self.grocery.mark_delivered(order["provider_ref"])
        plan = repo.get_plan(self.db, hid, order["plan_id"])
        self._say(hid, f"📦 Groceries from {order['store']} delivered and added to stock.")
        if plan["state"] == "briefed" and plan["brief"] and plan["brief"]["wait"]:
            wait = plan["brief"]["wait"]
            self._cook_say(hid, cookmsgs.render("delivered", h["cook_language"], wait=cookmsgs.dish_names(wait)))
            repo.update_plan(self.db, hid, plan["id"], brief={"start": plan["chosen"], "wait": []})
        elif plan["state"] == "ordered":
            repo.update_plan(self.db, hid, plan["id"], state="ready")

    # ------------------------------------------------------------------ cook chat
    def handle_cook(self, hid: str, text: str, voice: bool = True) -> None:
        h = self._h(hid)
        lang = h["cook_language"]
        plan = repo.latest_plan(self.db, hid)
        tr = self.speech.transcribe(text, lang) if voice else Transcript(text, 1.0, lang)
        repo.add_message(self.db, hid, "cook", "user", text, {"voice": True} if voice else None)
        if tr.confidence < LOW_CONFIDENCE:
            repo.audit(self.db, hid, "cook_low_confidence", confidence=tr.confidence)
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
        self._say(hid, f"❓ The cook said something I couldn't understand: “{text}”. I asked her to rephrase.")
        self._cook_say(hid, cookmsgs.render("help", lang))

    def _cook_arrived(self, hid: str, plan: dict | None, lang: str) -> None:
        if not plan or plan["state"] == "closed":
            return self._cook_say(hid, cookmsgs.render("no_menu", lang))
        if plan["state"] == "briefed":
            b = plan["brief"] or {"start": plan["chosen"], "wait": []}
            return self._cook_say(hid, self._compose_brief(lang, plan["chosen"], b["start"], b["wait"]))
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

    def _apply_cook_intents(self, hid: str, plan: dict, intents: list[dict]) -> None:
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
        self._cook_say(hid, cookmsgs.render("noted", h["cook_language"]))
        self._say(hid, "👩‍🍳 *Cook update:* " + "; ".join(said) + ".")
        if plan["state"] == "closing":
            return
        if problem:
            return self._switch_dish(hid, plan, problem)
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
        new = feasible[0].recipe_ids
        repo.update_plan(self.db, hid, plan["id"], chosen=new, brief={"start": new, "wait": []})
        repo.audit(self.db, hid, "dish_switched", reason=reason, to=new)
        self._cook_say(hid, cookmsgs.render("switch", lang, dishes=cookmsgs.dish_names(new)))
        self._say(hid, f"🔁 Because of '{reason}', I switched today's meal to *{_names(new)}* and saved "
                       "this so future plans account for it.")

    # ------------------------------------------------------------------ S8
    def end_of_day(self, hid: str) -> None:
        plan = repo.latest_plan(self.db, hid)
        if not plan or plan["state"] not in ("briefed", "ready", "ordered"):
            return
        repo.update_plan(self.db, hid, plan["id"], state="closing")
        self._cook_say(hid, cookmsgs.render("eod", self._h(hid)["cook_language"]))
        self._say(hid, "🌙 Asked the cook what was used today. I'll reconcile stock from her answer.")

    def close_day(self, hid: str) -> dict | None:
        plan = repo.latest_plan(self.db, hid)
        if not plan or plan["state"] == "closed":
            return plan
        h = self._h(hid)
        day = plan["day"]
        if h["sim_date"] < day:
            repo.update_household(self.db, hid, sim_date=day)
        reported = set(plan["report"])
        estimated = inv.apply_usage(self.db, hid, inv.needs_for(plan["chosen"], self._scale(plan)), day, reported)
        for rid in plan["chosen"]:
            repo.add_meal(self.db, hid, day, rid, RECIPES[rid]["name"], plan["reviewed"])
        plan = repo.update_plan(self.db, hid, plan["id"], state="closed")
        repo.audit(self.db, hid, "day_closed", plan=plan["id"], reported=sorted(reported), estimated=estimated)
        msg = f"🌙 *Day closed.* Cooked: {_names(plan['chosen'])}."
        if reported:
            msg += f"\nFrom the cook: {', '.join(sorted(reported))}."
        if estimated:
            msg += ("\nI estimated usage for " + ", ".join(estimated) +
                    " and flagged them to re-confirm tonight, since the cook didn't report them.")
        self._say(hid, msg)
        return plan

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
