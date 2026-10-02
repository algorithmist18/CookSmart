import pytest

from cooksmart import inventory as inv, repo
from cooksmart.guards import GuardViolation, OrderAuthorization
from cooksmart.providers.payment import MockPaymentProvider
from tests.conftest import DAY


def stock(e, name):
    return inv.get(e.db, e.hid, name)


# ---------------------------------------------------------------- planning (S1/S2)
def test_menu_covers_expiring_items(env):
    env.agent.nightly_review(env.hid)
    plan = env.plan()
    from cooksmart.recipes import RECIPES
    used = {i for p in plan["proposals"] for rid in p["recipe_ids"] for i in RECIPES[rid]["needs"]}
    assert {"tomato", "spinach"} <= used          # the two things about to spoil
    assert plan["state"] == "review"


def test_doubtful_stock_is_not_planned_around(env):
    inv.mark_uncertain(env.db, env.hid, "spinach")
    env.agent.nightly_review(env.hid)
    plan = env.plan()
    assert "spinach" in env.owner()[-1]            # asks about it
    assert all("spinach" not in p["reason"] for p in plan["proposals"])
    assert all(not any(g["name"] == "spinach" for g in p["gaps"]) or not p["feasible"]
               for p in plan["proposals"])


def test_stale_perishables_are_not_trusted(env):
    repo.update_household(env.db, env.hid, sim_date="2026-10-06")  # 5 days since last confirmation
    env.agent.nightly_review(env.hid)
    assert "not sure about these" in env.owner()[-1]


def test_rejection_replans_then_offers_ordering_after_two_tries(env):
    env.agent.nightly_review(env.hid)
    first = [p["recipe_ids"][0] for p in env.plan()["proposals"]]
    env.agent.handle_owner(env.hid, "something else")
    second = [p["recipe_ids"][0] for p in env.plan()["proposals"]]
    assert not set(first) & set(second)
    env.agent.handle_owner(env.hid, "something else")
    env.agent.handle_owner(env.hid, "something else")
    assert "tried twice" in env.owner()[-1]


# ---------------------------------------------------------------- feasibility + gap (S4/S5)
def test_partial_quantity_counts_as_missing(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "aloo gobi")   # needs 400 g cauliflower, have 300
    gaps = {g["name"]: g for g in env.plan()["gaps"]}
    assert gaps["cauliflower"]["reason"] == "partial"
    assert "short" in " ".join(env.owner())


def test_owner_correction_resolves_gap(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    assert env.plan()["state"] == "approval"
    env.agent.handle_owner(env.hid, "cream 100 ml")
    assert env.plan()["state"] == "ready"
    assert env.orders() == []


# ---------------------------------------------------------------- approve mode (S6)
def test_approve_mode_never_orders_without_tap(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    assert env.plan()["state"] == "approval" and env.orders() == []
    env.agent.handle_owner(env.hid, "approve")
    o = env.orders()[-1]
    assert o["status"] == "accepted" and o["authorization"] == "owner_tap"
    assert env.plan()["state"] == "ordered"


def test_decline_holds_without_buying(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "No, hold it")
    assert env.plan()["state"] == "held" and env.orders() == []


# ---------------------------------------------------------------- auto mode
def test_auto_mode_orders_within_cap(env):
    env.agent.set_settings(env.hid, order_mode="auto", auto_cap=500)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    o = env.orders()[-1]
    assert o["authorization"] == "auto_policy" and o["total"] <= 500
    assert env.plan()["state"] == "ordered"


def test_auto_mode_asks_when_above_cap(env):
    env.agent.set_settings(env.hid, order_mode="auto", auto_cap=10)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    assert env.orders() == [] and env.plan()["state"] == "approval"
    assert "above your auto-order limit" in " ".join(env.owner())


def test_silence_never_orders_even_in_auto_mode(env):
    env.agent.set_settings(env.hid, order_mode="auto", auto_cap=500)
    env.agent.nightly_review(env.hid)
    from cooksmart.planner import PlanContext, enrich
    ctx = PlanContext(cook_day=env.plan()["day"], stock=inv.available(env.db, env.hid, DAY, env.plan()["day"]))
    repo.update_plan(env.db, env.hid, env.plan()["id"], proposals=[enrich(["palak_paneer"], ctx).as_dict()])
    env.agent.cutoff(env.hid)
    plan = env.plan()
    assert plan["chosen"] == ["palak_paneer"] and plan["reviewed"] is False
    assert plan["state"] == "held" and env.orders() == []
    env.agent.handle_owner(env.hid, "approve")       # an explicit tap still works
    assert env.orders()[-1]["authorization"] == "owner_tap"


def test_approval_timeout_holds_and_reminds_next_night(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.cutoff(env.hid)
    assert env.plan()["state"] == "held" and env.orders() == []
    env.agent.nightly_review(env.hid)
    assert "was never approved" in env.owner()[-1]


def test_authorization_cannot_be_forged():
    with pytest.raises(GuardViolation):
        OrderAuthorization("owner_tap", 1, 9999.0)


# ---------------------------------------------------------------- failures
def test_payment_failure_means_no_order(env):
    env.controls.payment_fails = True
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "approve")
    assert env.orders()[-1]["status"] == "payment_failed"
    assert env.plan()["state"] == "approval"
    assert "didn't go through" in env.owner()[-1]


def test_mandate_ceiling_needs_fresh_tap():
    p = MockPaymentProvider(__import__("cooksmart.providers.controls", fromlist=["x"]).MockControls())
    assert not p.charge(3000, 2000, fresh_tap=False).ok
    assert p.charge(3000, 2000, fresh_tap=True).ok


def test_out_of_stock_everywhere_offers_other_dish_never_substitutes(env):
    env.controls.out_of_stock = {"cream"}
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    assert env.orders() == []
    plan = env.plan()
    assert plan["state"] == "review" and plan["chosen"] == []
    assert "out of stock everywhere" in " ".join(env.owner())


def test_overpriced_everywhere_is_reported(env):
    env.controls.price_factor = 4.0
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    assert env.orders() == [] and "overpriced" in " ".join(env.owner())


def test_cancel_after_accept_is_detected_and_reordered_elsewhere(env):
    env.controls.cancel_after_accept = True
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "approve")
    first = env.orders()[-1]
    env.controls.cancel_after_accept = False
    env.agent.check_orders(env.hid)
    assert repo.get_order(env.db, env.hid, first["id"])["status"] == "cancelled"
    plan = env.plan()
    assert plan["state"] == "approval" and plan["offer"]["store"] != first["store"]


def test_dispatch_never_promises_same_hour(env):
    from cooksmart.providers.dispatch import MockDispatchProvider
    s = MockDispatchProvider().check("560001", 500, needed_within_min=60)
    assert not s.serviceable and "no hyperlocal" in s.reason
    assert MockDispatchProvider().check("560001", 500, 2000).serviceable


# ---------------------------------------------------------------- door handshake
def _ordered(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "approve")


def test_cook_voice_releases_groceries(env):
    _ordered(env)
    assert env.agent.rider_arrives(env.hid, "cook")["released"]
    assert stock(env, "cream")["qty"] >= 50
    assert env.orders()[-1]["status"] == "delivered"


def test_stranger_is_refused_until_correct_otp(env):
    _ordered(env)
    r = env.agent.rider_arrives(env.hid, "stranger")
    assert not r["released"] and r["otp_required"]
    assert stock(env, "cream") is None
    assert not env.agent.door_otp(env.hid, "0000")["released"]
    otp = repo.list_orders(env.db, env.hid)[-1]["otp"]
    assert env.agent.door_otp(env.hid, otp)["released"]
    assert stock(env, "cream")["qty"] >= 50


# ---------------------------------------------------------------- cook handoff + voice (S7)
def test_brief_when_everything_in_stock(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    assert "पालक दाल" in env.cook()[0] and env.plan()["state"] == "briefed"


def test_cook_told_what_to_start_when_groceries_late(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "approve")        # cream is on its way
    # two-dish day: dal is makeable now, paneer waits for the cream
    repo.update_plan(env.db, env.hid, env.plan()["id"], chosen=["palak_dal", "palak_paneer"])
    env.agent.morning_handoff(env.hid)
    brief = env.cook()[-1]
    assert "पालक दाल" in brief and "शुरू करें" in brief
    assert env.plan()["brief"]["wait"] == ["palak_paneer"]
    env.agent.rider_arrives(env.hid, "cook")
    assert "सामान पहुँच गया" in env.cook()[-1]


def test_cook_never_left_waiting_with_nothing_to_start(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "approve")
    env.agent.morning_handoff(env.hid)
    assert "कटाई-तैयारी" in env.cook()[-1]


def test_nothing_ordered_so_cook_gets_dish_from_stock(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.cutoff(env.hid)                         # approval never came
    env.agent.morning_handoff(env.hid)
    assert env.orders() == []
    chosen = env.plan()["chosen"]
    assert chosen and chosen != ["palak_paneer"]
    assert "Switched" in " ".join(env.owner())


def test_low_confidence_voice_is_never_acted_on(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    before = stock(env, "paneer")["qty"]
    env.controls.stt_low_confidence = True
    env.agent.handle_cook(env.hid, "paneer khatam")
    assert "आवाज़ साफ़ नहीं आई" in env.cook()[-1]
    assert stock(env, "paneer")["qty"] == before
    assert env.plan()["pending"] is None


def test_cook_report_needs_readback_confirmation(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "paneer khatam")
    assert "सही है?" in env.cook()[-1]
    assert stock(env, "paneer")["qty"] == 200          # not applied yet
    env.agent.handle_cook(env.hid, "nahi")
    assert stock(env, "paneer")["qty"] == 200
    env.agent.handle_cook(env.hid, "paneer khatam")
    env.agent.handle_cook(env.hid, "haan")
    assert stock(env, "paneer")["qty"] == 0


def test_stove_broken_switches_to_no_stove_dish_and_remembers(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "gas kharab hai")
    env.agent.handle_cook(env.hid, "haan")
    chosen = env.plan()["chosen"]
    from cooksmart.recipes import RECIPES
    assert chosen and not RECIPES[chosen[0]]["stove"]
    assert any("stove" in m["note"] for m in repo.list_memory(env.db, env.hid))


def test_cook_ingredient_gone_mid_day_switches_dish(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "palak khatam")
    env.agent.handle_cook(env.hid, "haan")
    assert env.plan()["chosen"] != ["palak_dal"]


# ---------------------------------------------------------------- reconciliation (S8)
def test_day_close_updates_stock_and_flags_unreported(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    env.agent.end_of_day(env.hid)
    env.agent.handle_cook(env.hid, "palak 50 gram bacha")
    env.agent.handle_cook(env.hid, "haan")
    env.agent.close_day(env.hid)
    assert stock(env, "spinach")["qty"] == 50 and stock(env, "spinach")["confidence"] == "confirmed"
    assert stock(env, "dal")["qty"] == 350 and stock(env, "dal")["confidence"] == "uncertain"
    assert env.plan()["state"] == "closed"
    assert repo.recent_meals(env.db, env.hid, "2026-01-01")[0]["dish_id"] == "palak_dal"


def test_repeat_penalty_after_closing_a_day(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    env.agent.close_day(env.hid)
    inv.confirm_all(env.db, env.hid, env.plan()["day"])
    env.agent.nightly_review(env.hid)
    mains = [p["recipe_ids"][0] for p in env.plan()["proposals"]]
    assert "dal_tadka" not in mains


# ---------------------------------------------------------------- boundaries
def test_cook_chat_never_contains_money_stock_or_orders(env):
    env.agent.set_settings(env.hid, order_mode="auto", auto_cap=500)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "paneer khatam")
    env.agent.handle_cook(env.hid, "haan")
    env.agent.rider_arrives(env.hid, "cook")
    env.agent.end_of_day(env.hid)
    env.agent.close_day(env.hid)
    blob = " ".join(env.cook()).lower()
    for banned in ("₹", "rs.", "order", "stock", "approve", "otp", "quickcart", "freshbasket", "payment"):
        assert banned not in blob


def test_households_are_isolated(env):
    repo.create_household(env.db, "other", "Other", DAY, preferences={})
    inv.set_qty(env.db, "other", "paneer", 999, DAY)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "paneer 5 g")
    assert inv.get(env.db, "other", "paneer")["qty"] == 999
    assert repo.list_messages(env.db, "other", "owner") == []
    assert repo.latest_plan(env.db, "other") is None
