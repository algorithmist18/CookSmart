"""Scenario library: start the household in a specific situation, optionally with a mock rail misbehaving,
and (optionally) play a scripted conversation so you can watch the whole thing unfold.

Stock rows: (item, qty, days_until_use_by | None, days_since_last_confirmed).
Script steps: ("trigger", name) | ("owner", text) | ("cook", text) | ("door", sample) | ("otp",) |
              ("controls", {...}); any step may carry a trailing condition: "state:approval" | "open_order".
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import inventory as inv
from . import repo
from .db import DB
from .gnani_kb import DEMO_PROFILE
from . import callresult
from .providers.controls import MockControls
from .recipes import RECIPES

BASE = inv.DEFAULT_STOCK

# ---- scripted days (reused building blocks)
ARRIVE = [("cook", "namaste, main aa gayi"), ("cook", "haan")]
EVENING = [("cook", "khana ban gaya"), ("cook", "paneer poora lag gaya, 2 tamatar bache"), ("cook", "haan"),
           ("trigger", "close_day")]


@dataclass
class Scenario:
    id: str
    title: str
    emoji: str
    blurb: str
    hint: str
    stock: list = field(default_factory=lambda: list(BASE))
    prefs: dict = field(default_factory=lambda: {"diet": "vegetarian"})
    family: int = 4
    next: dict = field(default_factory=dict)
    history: list = field(default_factory=list)          # (days_ago, dish_id)
    controls: dict = field(default_factory=dict)
    auto_cap: int | None = None
    script: list = field(default_factory=list)


SCENARIOS: list[Scenario] = [
    Scenario("classic", "A normal evening", "🍲",
             "Tomatoes and spinach are about to spoil; cream is missing for palak paneer.",
             "Reply *palak paneer*: cream is missing, so the agent finds an order (or asks, depending on the mode).",
             script=[("trigger", "nightly_review"), ("owner", "palak paneer"), ("owner", "approve", "state:approval"),
                     *ARRIVE, ("door", "cook", "open_order"), *EVENING]),
    Scenario("spoilage_crunch", "Too much is expiring", "⏳",
             "Six items expire tomorrow and the last two days were already dal and palak paneer.",
             "Not everything can be used without repeating a dish. Read the trade-offs the agent explains.",
             stock=[("tomato", 5, 1, 0), ("spinach", 400, 1, 0), ("capsicum", 3, 1, 0), ("mushroom", 250, 1, 0),
                    ("curd", 400, 1, 0), ("cucumber", 3, 1, 0), ("paneer", 200, 3, 0), ("peas", 250, 2, 0),
                    ("cabbage", 500, 2, 0), ("onion", 6, 15, 0), ("potato", 4, 14, 0), ("dal", 500, None, 0),
                    ("atta", 1000, None, 0), ("rice", 1000, None, 0)],
             history=[(1, "dal_tadka"), (2, "palak_paneer")],
             script=[("trigger", "nightly_review"), ("owner", "1 and 2"), ("trigger", "morning"),
                     ("cook", "haan")]),
    Scenario("stale_fridge", "Nobody updated the fridge", "🕸️",
             "Stock was last confirmed 5 days ago, so the agent won't trust the perishables.",
             "Reply *all good* to confirm everything, or fix individual items (*tomato 2*).",
             stock=[(n, q, e, 5) for n, q, e, _ in BASE],
             script=[("trigger", "nightly_review"), ("owner", "all good"), ("owner", "1")]),
    Scenario("guests", "Guests tomorrow", "👥",
             "Four guests are coming, so quantities double and partial stock becomes a gap.",
             "Watch the menu scale (x2) and the shopping list grow. Try *change menu* after changing guests.",
             next={"guests": 4},
             stock=[("rice", 500, None, 0), ("atta", 400, None, 0), ("dal", 200, None, 0), ("onion", 4, 15, 0),
                    ("tomato", 3, 3, 0), ("paneer", 200, 4, 0), ("peas", 250, 5, 0), ("curd", 400, 4, 0)],
             script=[("trigger", "nightly_review"), ("owner", "1"), ("owner", "approve", "state:approval"),
                     *ARRIVE, ("door", "cook", "open_order")]),
    Scenario("jain", "Jain household", "🕉️",
             "No onion, potato or carrot, ever.",
             "Every option avoids root vegetables even though onions and potatoes are in the fridge.",
             prefs={"diet": "jain"},
             stock=BASE + [("lauki", 500, 3, 0), ("cabbage", 400, 4, 0), ("brinjal", 500, 4, 0)],
             script=[("trigger", "nightly_review"), ("owner", "1")]),
    Scenario("fasting", "Navratri fasting day", "🪔",
             "Only vrat dishes: sabudana, samak, kuttu, potato, curd, fruit.",
             "The agent plans a fasting menu and never suggests rice, dal or roti.",
             next={"fasting": True},
             stock=[("potato", 6, 15, 0), ("sabudana", 400, None, 0), ("peanuts", 250, None, 0),
                    ("samak", 300, None, 0), ("kuttu", 300, None, 0), ("curd", 400, 3, 0),
                    ("cucumber", 3, 3, 0), ("banana", 6, 3, 0), ("apple", 4, 6, 0)],
             script=[("trigger", "nightly_review"), ("owner", "1")]),
    Scenario("non_veg", "Non-veg family", "🍗",
             "Chicken must be cooked tomorrow or it spoils; eggs are on hand too.",
             "Menus now include chicken and egg dishes, built around the chicken that expires first.",
             prefs={"diet": "nonveg"},
             stock=[("chicken", 500, 1, 0), ("egg", 6, 4, 0), ("onion", 6, 15, 0), ("tomato", 4, 4, 0),
                    ("atta", 1000, None, 0), ("rice", 1000, None, 0), ("dal", 500, None, 0),
                    ("bread", 8, 3, 0), ("curd", 400, 4, 0)],
             script=[("trigger", "nightly_review"), ("owner", "1")]),
    Scenario("light_day", "Something light please", "🥗",
             "Light and healthy only: no cream, no deep frying, nothing heavy.",
             "Menus favour dal, khichdi, raita and lightly cooked sabzi.",
             next={"light": True},
             script=[("trigger", "nightly_review"), ("owner", "1")]),
    Scenario("empty_pantry", "Nearly empty kitchen", "🫙",
             "Almost nothing at home. The shopping list is big and your auto-order limit is ₹300.",
             "In auto mode a big basket is over the limit, so the agent asks first.",
             stock=[("onion", 2, 10, 0), ("tomato", 1, 2, 0), ("rice", 200, None, 0)], auto_cap=300,
             script=[("trigger", "nightly_review"), ("owner", "1"), ("owner", "approve", "state:approval"),
                     *ARRIVE, ("door", "cook", "open_order")]),
    Scenario("cook_on_leave", "Cook is off tomorrow", "🏖️",
             "The cook messages that she can't come. The agent switches to a no-cook menu.",
             "Notice that the cook is not messaged on a day off.",
             script=[("cook", "kal main nahi aa paungi, tabiyat theek nahi"), ("trigger", "nightly_review"),
                     ("owner", "1"), ("trigger", "morning")]),
    Scenario("stove_trouble", "The gas runs out", "🔥",
             "The cook arrives and tells you the gas is not working.",
             "The agent reads it back, switches to a no-stove meal, and remembers the problem.",
             script=[("trigger", "nightly_review"), ("owner", "dal tadka"), *ARRIVE,
                     ("cook", "gas kharab hai"), ("cook", "haan")]),
    Scenario("cooker_broken", "Pressure cooker broke", "🫕",
             "Dal and rice normally need the cooker.",
             "Try telling the cook chat *cooker kharab hai* after the brief.",
             script=[("trigger", "nightly_review"), ("owner", "dal tadka"), *ARRIVE,
                     ("cook", "cooker kharab hai"), ("cook", "haan")]),
    Scenario("item_spoiled", "Spinach went bad", "🤢",
             "The cook finds the spinach rotten when she starts cooking.",
             "The cook says *palak kharab ho gayi*. The agent confirms, logs the waste and switches.",
             script=[("trigger", "nightly_review"), ("owner", "palak dal"), *ARRIVE,
                     ("cook", "palak kharab ho gayi"), ("cook", "haan")]),
    Scenario("owner_silent", "You don't reply", "🙈",
             "The owner doesn't answer before the cutoff.",
             "The agent cooks its top pick, flags it unreviewed, and orders nothing even in auto mode.",
             script=[("trigger", "nightly_review"), ("trigger", "cutoff"), ("trigger", "morning")]),
    Scenario("payment_declines", "Payment gets declined", "💳",
             "The bank declines the grocery payment.",
             "The agent says nothing was ordered and waits for you to retry.",
             controls={"payment_fails": True},
             script=[("trigger", "nightly_review"), ("owner", "palak paneer"), ("owner", "approve", "state:approval"),
                     ("controls", {"payment_fails": False}), ("owner", "approve")]),
    Scenario("order_cancelled", "Store cancels the order", "🚫",
             "The store accepts your order, then cancels it.",
             "The agent notices on re-check and finds another store.",
             controls={"cancel_after_accept": True},
             script=[("trigger", "nightly_review"), ("owner", "palak paneer"), ("owner", "approve", "state:approval"),
                     ("controls", {"cancel_after_accept": False}), ("trigger", "check_orders"),
                     ("owner", "approve", "state:approval")]),
    Scenario("out_of_stock", "Cream is out of stock", "📭",
             "No store has cream.",
             "The agent never swaps in something else silently. It offers other meals.",
             controls={"out_of_stock": ["cream"]},
             script=[("trigger", "nightly_review"), ("owner", "palak paneer")]),
    Scenario("overpriced", "Prices are crazy", "💸",
             "Every store charges 3x today.",
             "The agent refuses to recommend an overpriced order and suggests meals from stock.",
             controls={"price_factor": 3.0},
             script=[("trigger", "nightly_review"), ("owner", "palak paneer")]),
    Scenario("late_delivery", "Groceries will be late", "🐢",
             "Delivery ETAs are pushed past the cook's arrival.",
             "The cook is told what to start with, then gets a message when the rider arrives.",
             controls={"eta_delay_min": 700},
             script=[("trigger", "nightly_review"), ("owner", "palak paneer + roti"), ("owner", "approve", "state:approval"),
                     *ARRIVE, ("door", "cook", "open_order")]),
    Scenario("misheard_voice", "Cook's voice note is unclear", "🎙️",
             "Speech recognition can't make out the cook (the Bengali-heard-as-Hindi problem).",
             "The agent refuses to act on unclear audio and asks her to repeat or type.",
             controls={"stt_low_confidence": True},
             script=[("trigger", "nightly_review"), ("owner", "dal tadka"), ("trigger", "morning"),
                     ("cook", "paneer khatam"), ("controls", {"stt_low_confidence": False}),
                     ("cook", "paneer khatam"), ("cook", "haan")]),
    Scenario("stranger_at_door", "A stranger collects the delivery", "🕵️",
             "The rider is met by someone whose voice doesn't match the cook's.",
             "The groceries are not handed over until the correct OTP is entered.",
             script=[("trigger", "nightly_review"), ("owner", "palak paneer"), ("owner", "approve", "state:approval"),
                     ("trigger", "morning"), ("door", "stranger", "open_order"), ("otp",)]),
]
FAMILY = {k: v for k, v in DEMO_PROFILE.items() if k not in ("diet",)} | {"diet": "vegetarian"}
CALL_FAMILY = FAMILY | {"cook_channel": "call"}

SCENARIOS += [
    Scenario("allergy_family", "A child with a peanut allergy", "🥜",
             "Aarav (8) is allergic to peanuts; Papa needs less salt and sugar; Dadi needs soft food.",
             "Try asking for *poha*: it's blocked (it has peanuts). Every option avoids peanuts, and the cook is warned every time.",
             prefs=FAMILY, script=[("trigger", "nightly_review"), ("owner", "poha"), ("owner", "1")]),
    Scenario("morning_call", "The agent phones the cook", "📞",
             "Instead of a chat message, the Gnani voice agent calls the cook with today's brief: what to use first, "
             "taste tips, allergy cautions. (Simulated here: no real call is placed.)",
             "Watch the call appear in *Cook calls*, then use *Simulate the call result* to see what she reported.",
             prefs=CALL_FAMILY, script=[("trigger", "nightly_review"), ("owner", "palak dal and roti"), ("trigger", "morning"),
                                        ("call_result", "item_finished"), ("trigger", "end_of_day"), ("call_result", "reconcile")]),
    Scenario("call_gas_problem", "She reports a gas problem on the call", "☎️",
             "The cook tells the voice agent the gas isn't working and confirms it.",
             "The meal is switched to a no-stove one, and the owner is told. Nothing is applied that she didn't confirm.",
             prefs=CALL_FAMILY, script=[("trigger", "nightly_review"), ("owner", "dal tadka"), ("trigger", "morning"),
                                        ("call_result", "gas_problem")]),
    Scenario("call_unanswered", "The cook doesn't pick up", "📵",
             "The call rings out. The agent falls back to a voice note so she isn't left waiting.",
             "The same brief arrives in the cook's chat.",
             prefs=CALL_FAMILY, script=[("trigger", "nightly_review"), ("owner", "dal tadka"), ("trigger", "morning"),
                                        ("call_result", "no_answer")]),
    Scenario("call_unconfirmed", "She mentions something but doesn't confirm", "🤔",
             "She says paneer is finished, but the line cuts before she confirms the read-back.",
             "Stock is left alone and the owner is told it wasn't applied.",
             prefs=CALL_FAMILY, script=[("trigger", "nightly_review"), ("owner", "dal tadka"), ("trigger", "morning"),
                                        ("call_result", "unconfirmed")]),
]
BY_ID = {s.id: s for s in SCENARIOS}


def catalog() -> list[dict]:
    return [{"id": s.id, "title": s.title, "emoji": s.emoji, "blurb": s.blurb, "hint": s.hint}
            for s in SCENARIOS]


def load(db: DB, controls: MockControls, hid: str, sid: str) -> Scenario:
    sc = BY_ID[sid]
    today = dt.date.today().isoformat()
    repo.wipe_household_data(db, hid)
    controls.reset()
    controls.update(sc.controls)
    prefs = dict(sc.prefs)
    prefs.setdefault("dislikes", [])
    prefs.setdefault("likes", [])
    if sc.next:
        prefs["next"] = dict(sc.next)
    fields = dict(preferences=prefs, family_size=sc.family, sim_date=today, cook_voice_enrolled=1)
    if sc.auto_cap is not None:
        fields["auto_cap"] = sc.auto_cap
    repo.update_household(db, hid, **fields)
    inv.seed(db, hid, today, sc.stock)
    for days_ago, dish in sc.history:
        repo.add_meal(db, hid, (dt.date.today() - dt.timedelta(days=days_ago)).isoformat(), dish,
                      RECIPES[dish]["name"], True)
    repo.audit(db, hid, "scenario_loaded", scenario=sid)
    return sc


def _cond(db: DB, hid: str, cond: str | None) -> bool:
    if not cond:
        return True
    plan = repo.latest_plan(db, hid)
    if cond.startswith("state:"):
        return bool(plan) and plan["state"] == cond.split(":", 1)[1]
    if cond == "open_order":
        return any(o["status"] == "accepted" for o in repo.list_orders(db, hid))
    return True


def play(agent, db: DB, controls: MockControls, hid: str, script: list) -> None:
    """Run a script instantly; the UI replays the resulting messages with typing delays."""
    for step in script:
        kind, args, cond = step[0], step[1:], None
        if args and isinstance(args[-1], str) and (args[-1].startswith("state:") or args[-1] == "open_order"):
            cond, args = args[-1], args[:-1]
        if not _cond(db, hid, cond):
            continue
        if kind == "trigger":
            getattr(agent, {"morning": "morning_handoff"}.get(args[0], args[0]))(hid)
        elif kind == "owner":
            agent.handle_owner(hid, args[0])
        elif kind == "cook":
            agent.handle_cook(hid, args[0], voice=True)
        elif kind == "door":
            agent.rider_arrives(hid, args[0])
        elif kind == "otp":
            order = next((o for o in reversed(repo.list_orders(db, hid)) if o["otp"]), None)
            if order:
                agent.door_otp(hid, order["otp"])
        elif kind == "controls":
            controls.update(args[0])
        elif kind == "call_result":                      # a Gnani-shaped webhook through the real handler
            call = next((c for c in repo.list_calls(db, hid, 20) if c["status"] == "placed"), None)
            plan = repo.latest_plan(db, hid)
            if call:
                menu = list(inv.needs_for(plan["chosen"])) if plan and plan["chosen"] else []
                stocked = [i["name"] for i in inv.list_items(db, hid) if i["qty"] > 0]
                full = repo.get_call(db, call["reference_id"])
                agent.handle_call_result(callresult.simulated_payload(args[0], full,
                                                                      callresult.pick_items(args[0], menu, stocked)))
