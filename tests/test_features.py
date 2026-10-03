"""Recipes, conditions, cook conversation and scenarios."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from cooksmart import inventory as inv, repo, scenarios
from cooksmart.api import create_app
from cooksmart.config import Settings
from cooksmart.db import DB
from cooksmart.nlu import parse_cook, parse_owner
from cooksmart.recipes import ALIASES, DAIRY, ITEMS, JAIN_BANNED, RECIPES
from tests.conftest import DAY


def load(env, sid):
    return scenarios.load(env.db, env.controls, env.hid, sid)


# ------------------------------------------------------------------ recipe book integrity
def test_recipe_book_is_consistent():
    assert len(RECIPES) >= 45
    for rid, r in RECIPES.items():
        assert r["hi"] and r["name"], rid
        assert r["course"] in {"sabzi", "dal", "carb", "one_pot", "breakfast", "side", "vrat"}, rid
        assert r["diet"] in {"veg", "egg", "nonveg"}, rid
        for item, (qty, unit) in r["needs"].items():
            assert item in ITEMS and qty > 0 and unit == ITEMS[item]["unit"], (rid, item)
    for item in ITEMS:
        assert ALIASES.get(item), item
        assert ITEMS[item]["hi"] and ITEMS[item]["pack"] > 0 and ITEMS[item]["price"] > 0


def test_every_scenario_is_loadable_and_consistent():
    assert len(scenarios.SCENARIOS) >= 20
    for sc in scenarios.SCENARIOS:
        assert sc.title and sc.blurb and sc.hint and sc.script, sc.id
        for item, *_ in sc.stock:
            assert item in ITEMS, (sc.id, item)


@pytest.mark.parametrize("mode", ["approve", "auto"])
@pytest.mark.parametrize("sid", [s.id for s in scenarios.SCENARIOS])
def test_every_scenario_plays_through_cleanly(env, sid, mode):
    repo.update_household(env.db, env.hid, order_mode=mode)
    sc = load(env, sid)
    scenarios.play(env.agent, env.db, env.controls, env.hid, sc.script)
    assert env.owner(), "the owner should have been told something"
    blob = " ".join(env.cook()).lower()
    for banned in ("₹", "rs.", "order", "stock", "approve", "otp", "quickcart", "freshbasket", "payment"):
        assert banned not in blob, (sid, banned)


# ------------------------------------------------------------------ meals, not single dishes
def test_menus_are_composed_meals_without_duplicates(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "skip")                  # breakfast skipped: lunch options
    props = env.plan()["proposals"]
    assert any(len(p["recipe_ids"]) > 1 for p in props)
    sets = [frozenset(p["recipe_ids"]) for p in props]
    assert len(sets) == len(set(sets))
    for p in props:
        courses = [RECIPES[i]["course"] for i in p["recipe_ids"]]
        if courses[0] in ("sabzi", "dal"):
            assert "carb" in courses            # a sabzi or dal always comes with roti/rice


def test_choosing_option_selects_every_dish_in_it(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "skip")
    first = env.plan()["proposals"][0]["recipe_ids"]
    env.agent.handle_owner(env.hid, "1")                     # lunch option 1 (the rest of the day takes option 1 too)
    assert env.plan()["meals"]["lunch"] == first and set(first) <= set(env.plan()["chosen"])


def test_multiple_dishes_in_one_request(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka and jeera rice")
    assert env.plan()["chosen"] == ["dal_tadka", "jeera_rice"]


# ------------------------------------------------------------------ conditions
def test_guests_scale_quantities(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "4 guests tomorrow")
    plan = env.plan()
    assert plan["flags"]["guests"] == 4 and plan["flags"]["scale"] == 2.0
    env.agent.handle_owner(env.hid, "dal tadka")
    gaps = {g["name"]: g for g in env.plan()["gaps"]}
    assert gaps == {} or all(g["need"] >= 2 for g in gaps.values())
    assert inv.needs_for(["dal_tadka"], 2.0)["dal"]["qty"] == 300


def test_flags_before_review_apply_to_next_night(env):
    env.agent.handle_owner(env.hid, "fasting tomorrow")
    assert repo.get_household(env.db, env.hid)["preferences"]["next"] == {"fasting": True}
    env.agent.nightly_review(env.hid)
    assert env.plan()["flags"]["fasting"] is True
    assert "next" not in repo.get_household(env.db, env.hid)["preferences"]


def test_fasting_day_only_offers_vrat_dishes(env):
    sc = load(env, "fasting")
    env.agent.nightly_review(env.hid)
    for p in env.plan()["proposals"]:
        assert all("vrat" in RECIPES[i]["tags"] for i in p["recipe_ids"]), p


def test_jain_never_uses_root_vegetables(env):
    load(env, "jain")
    env.agent.nightly_review(env.hid)
    for p in env.plan()["proposals"]:
        for i in p["recipe_ids"]:
            assert not set(RECIPES[i]["needs"]) & JAIN_BANNED


def test_vegetarian_household_is_never_offered_meat_or_egg(env):
    env.agent.nightly_review(env.hid)
    for p in env.plan()["proposals"]:
        assert all(RECIPES[i]["diet"] == "veg" for i in p["recipe_ids"])


def test_non_veg_household_gets_chicken_that_is_about_to_spoil(env):
    load(env, "non_veg")
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "skip")
    mains = {i for p in env.plan()["proposals"] for i in p["recipe_ids"]}
    assert "chicken_curry" in mains


def test_no_dairy_preference(env):
    env.agent.handle_owner(env.hid, "no dairy")
    env.agent.nightly_review(env.hid)
    for p in env.plan()["proposals"]:
        for i in p["recipe_ids"]:
            assert not set(RECIPES[i]["needs"]) & DAIRY


def test_light_day_avoids_heavy_dishes(env):
    load(env, "light_day")
    env.agent.nightly_review(env.hid)
    assert env.plan()["flags"]["light"]
    for p in env.plan()["proposals"]:
        assert all("heavy" not in RECIPES[i]["tags"] for i in p["recipe_ids"])


def test_changing_preferences_replans_the_open_menu(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "jain")
    for p in env.plan()["proposals"]:
        assert not any(set(RECIPES[i]["needs"]) & JAIN_BANNED for i in p["recipe_ids"])
    assert "Re-planned" in " ".join(env.owner()) or "Saved" in " ".join(env.owner())


def test_change_menu_starts_over(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    assert env.plan()["chosen"]
    env.agent.handle_owner(env.hid, "change menu")
    assert env.plan()["state"] == "review" and env.plan()["chosen"] == []


# ------------------------------------------------------------------ the cook conversation
def test_bare_haan_after_the_brief_is_understood(env):
    """Regression: the brief asks 'samajh gaye? haan bolen' and used to answer 'didn't understand'."""
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    before = len(env.cook())
    env.agent.handle_cook(env.hid, "haan")
    assert "समझ नहीं आया" not in env.cook()[-1]
    assert "confirmed today's menu" in " ".join(env.owner())
    assert len(env.cook()) == before + 2        # the cook's "haan" plus exactly one reply


def test_cook_saying_no_to_the_brief_hears_it_again(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "nahi")
    assert "दाल तड़का" in env.cook()[-1]


@pytest.mark.parametrize("phrase", ["namaste, main aa gayi", "I'm here", "what do I cook today?", "आज क्या बनाना है?"])
def test_cook_arrival_phrases_trigger_the_brief(env, phrase):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.handle_cook(env.hid, phrase)
    assert env.plan()["state"] == "briefed"
    assert "दाल तड़का" in env.cook()[-1]


def test_cook_greeting_gets_a_friendly_reply_not_an_error(env):
    env.agent.handle_cook(env.hid, "namaste")
    assert "नमस्ते" in env.cook()[-1] and "समझ नहीं आया" not in env.cook()[-1]


def test_cook_nonsense_gets_help_and_owner_is_told(env):
    env.agent.handle_cook(env.hid, "blah blah zzz")
    assert "आप ऐसे बोल सकते हैं" in env.cook()[-1]
    assert "couldn't understand" in env.owner()[-1]


@pytest.mark.parametrize("phrase", ["khana ban gaya", "done", "kaam ho gaya"])
def test_cook_done_starts_the_evening_reconciliation(env, phrase):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, phrase)
    assert env.plan()["state"] == "closing"


def test_cook_leave_message_switches_next_day_to_no_cook_and_cook_is_not_messaged(env):
    env.agent.handle_cook(env.hid, "kal main nahi aa paungi")
    env.agent.nightly_review(env.hid)
    assert env.plan()["flags"]["cook_off"]
    for p in env.plan()["proposals"]:
        assert all(not RECIPES[i]["tools"] for i in p["recipe_ids"])
    env.agent.handle_owner(env.hid, "1")
    cook_msgs = len(env.cook())
    env.agent.morning_handoff(env.hid)
    assert len(env.cook()) == cook_msgs
    assert "cook is off today" in " ".join(env.owner())


def test_spoiled_item_is_confirmed_logged_and_triggers_a_switch(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "palak kharab ho gayi")
    assert inv.get(env.db, env.hid, "spinach")["qty"] == 300      # not applied before confirmation
    env.agent.handle_cook(env.hid, "haan")
    assert inv.get(env.db, env.hid, "spinach")["qty"] == 0
    assert any(a["event"] == "item_spoiled" for a in repo.list_audit(env.db, env.hid))
    assert env.plan()["chosen"] != ["palak_dal"]


def test_cooker_broken_avoids_cooker_dishes(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "cooker kharab hai")
    env.agent.handle_cook(env.hid, "haan")
    for i in env.plan()["chosen"]:
        assert "cooker" not in RECIPES[i]["tools"]


def test_owner_can_relay_a_message_to_the_cook(env):
    env.agent.handle_owner(env.hid, "tell cook: kam mirch daliye")
    assert "kam mirch daliye" in env.cook()[-1]
    assert "Sent to the cook" in env.owner()[-1]


def test_cook_voice_notes_are_marked_as_voice(env):
    env.agent.handle_cook(env.hid, "namaste", voice=True)
    env.agent.handle_cook(env.hid, "namaste", voice=False)
    msgs = [m for m in repo.list_messages(env.db, env.hid, "cook") if m["sender"] == "user"]
    assert msgs[0]["payload"]["voice"] is True and msgs[1]["payload"] is None


def test_cook_readback_has_quick_reply_buttons(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    env.agent.handle_cook(env.hid, "no paneer left")
    last = repo.list_messages(env.db, env.hid, "cook")[-1]
    assert last["payload"]["buttons"] == ["हाँ", "नहीं"]


# ------------------------------------------------------------------ language
def test_cook_english_and_hindi_phrases():
    assert parse_cook("no paneer left")[0] == {"type": "used_up", "item": "paneer"}
    assert parse_cook("2 tomatoes left")[0]["type"] == "remaining"
    assert parse_cook("the stove is not working")[0] == {"type": "cannot_cook", "reason": "stove"}
    assert parse_cook("मैं आ गई")[0]["type"] == "arrived"
    assert parse_cook("टमाटर सड़ गए")[0] == {"type": "spoiled", "item": "tomato"}
    assert parse_cook("कल मैं नहीं आ सकती")[0]["type"] == "leave"
    assert parse_cook("")[0]["type"] == "unknown"


def test_owner_commands():
    assert parse_owner("6 guests tomorrow") == {"action": "flags", "flags": {"guests": 6}}
    assert parse_owner("fasting tomorrow")["flags"] == {"fasting": True}
    assert parse_owner("cook is off tomorrow")["flags"] == {"cook_off": True}
    assert parse_owner("jain")["prefs"] == {"diet": "jain"}
    assert parse_owner("non veg ok")["prefs"] == {"diet": "nonveg"}
    assert parse_owner("family of 5")["prefs"] == {"family_size": 5}
    assert parse_owner("tell cook: kam mirch")["action"] == "relay"
    assert parse_owner("palak paneer and roti") == {"action": "dish_request", "dishes": ["palak_paneer", "roti"]}
    assert parse_owner("rajma 300 g")["action"] == "stock"          # an ingredient, not the dish
    assert parse_owner("change menu")["action"] == "redo"
    assert parse_owner("help")["action"] == "help"


# ------------------------------------------------------------------ API + migration
def test_scenario_endpoints_and_next_step_guide():
    c = TestClient(create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:")))
    c.post("/api/households", json={"id": "h"})
    assert len(c.get("/api/scenarios").json()) >= 20
    state = c.get("/api/h/owner/state").json()
    assert state["next"]["step"] == 0 and state["next"]["action"] == {"kind": "trigger", "name": "nightly_review"}
    assert c.post("/api/h/scenario/nope").status_code == 404
    r = c.post("/api/h/scenario/classic?play=true").json()
    assert r["reset"] and r["played"]
    state = c.get("/api/h/owner/state").json()
    assert state["plan"]["state"] == "closed" and state["scenario"]["id"] == "classic"
    assert len(c.get("/api/h/cook/messages").json()) > 3
    c.post("/api/h/scenario/guests")                       # loading wipes the previous run
    assert c.get("/api/h/owner/messages").json() == []
    assert c.get("/api/h/owner/state").json()["household"]["preferences"]["next"] == {"guests": 4}


def test_old_databases_are_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE households (id TEXT PRIMARY KEY, name TEXT, sim_date TEXT);"
                      "CREATE TABLE plans (id INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT, day TEXT);")
    con.commit(); con.close()
    db = DB(path)
    cols = {r["name"] for r in db.query("PRAGMA table_info(plans)")}
    assert {"flags", "excluded"} <= cols
    assert "family_size" in {r["name"] for r in db.query("PRAGMA table_info(households)")}


# ------------------------------------------------------------------ the day: fridge + three meals
def test_every_item_has_a_fridge_view():
    from cooksmart import daystory
    from cooksmart.recipes import ITEMS
    assert [i for i in ITEMS if i not in daystory.ITEM_VIEW] == []
    assert all(daystory.view(i)["emoji"] for i in ITEMS)




# ------------------------------------------------------------------ breakfast, lunch and dinner planned separately
def _day_env():
    c = TestClient(create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:")))
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/scenario/classic")
    return c




def test_extra_meals_never_add_shortages_or_allergens():
    from cooksmart.planner import PlanContext, plan_day
    from cooksmart.recipes import RECIPES
    stock = {"poha": {"qty": 500, "unit": "g", "days_left": None}, "onion": {"qty": 6, "unit": "pcs", "days_left": None},
             "peanuts": {"qty": 100, "unit": "g", "days_left": None}, "paneer": {"qty": 400, "unit": "g", "days_left": 2},
             "atta": {"qty": 1000, "unit": "g", "days_left": None}, "tomato": {"qty": 4, "unit": "pcs", "days_left": 2}}
    ctx = PlanContext("2030-01-02", stock, preferences={"diet": "vegetarian", "members": [{"name": "A", "allergies": ["peanut"]}]})
    m = plan_day(["paneer_bhurji", "roti"], ctx)
    assert m["breakfast"] != ["poha"]                         # poha needs peanuts: never, with a peanut allergy
    assert all("peanuts" not in RECIPES[r]["needs"] for v in m.values() for r in v)


def test_claude_suggested_breakfast_and_dinner_are_validated():
    from cooksmart.planner import PlanContext, plan_day
    stock = {"poha": {"qty": 500, "unit": "g", "days_left": None}, "onion": {"qty": 6, "unit": "pcs", "days_left": None},
             "peanuts": {"qty": 100, "unit": "g", "days_left": None}, "atta": {"qty": 1000, "unit": "g", "days_left": None},
             "paneer": {"qty": 400, "unit": "g", "days_left": 2}, "tomato": {"qty": 4, "unit": "pcs", "days_left": 2}}
    ctx = PlanContext("2030-01-02", stock, preferences={"diet": "vegetarian"})
    m = plan_day(["paneer_bhurji", "roti"], ctx, breakfast=["poha"], dinner=["chicken_curry"])
    assert m["breakfast"] == ["poha"]                         # makeable from stock: kept
    assert "chicken_curry" not in m["dinner"]                 # not allowed (vegetarian): replaced by code


def test_cook_is_told_which_dish_is_for_which_meal():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    c.post("/api/h/owner/message", json={"text": "1"})
    c.post("/api/h/owner/message", json={"text": "approve"})
    c.post("/api/h/trigger/morning")
    plan = c.get("/api/h/owner/state").json()["plan"]
    cook = " ".join(m["text"] for m in c.get("/api/h/cook/messages").json())
    if plan["meals"]["breakfast"] or plan["meals"]["dinner"]:
        assert "ब्रेकफास्ट:" in cook and "लंच:" in cook and "डिनर:" in cook
    assert "₹" not in cook


# ------------------------------------------------------------------ ask breakfast + lunch, 15-minute delivery, eat-within window


def test_named_breakfast_respects_allergies():
    c = _day_env()
    c.post("/api/h/owner/message", json={"text": "Aarav is allergic to peanuts"})
    c.post("/api/h/trigger/nightly_review")
    c.post("/api/h/owner/message", json={"text": "breakfast poha, lunch dal tadka"})        # poha is made with peanuts
    st = c.get("/api/h/owner/state").json()
    assert st["plan"]["chosen"] == [] or "poha" not in st["plan"]["chosen"]
    assert "won't plan" in " ".join(m["text"] for m in c.get("/api/h/owner/messages").json())




def test_expiring_items_say_within_how_many_days():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    msgs = " ".join(m["text"] for m in c.get("/api/h/owner/messages").json())
    assert "Eat soon" in msgs and "within 2 days, by" in msgs
    spinach = next(i for i in c.get("/api/h/owner/state").json()["fridge"] if i["name"] == "spinach")
    assert spinach["within"] == 2 and spinach["use_by"]




def test_avoid_prefers_a_different_breakfast_but_falls_back_when_there_is_no_other():
    from cooksmart.planner import PlanContext, plan_day
    base = {"onion": {"qty": 6, "unit": "pcs", "days_left": None}, "peanuts": {"qty": 100, "unit": "g", "days_left": None},
            "poha": {"qty": 500, "unit": "g", "days_left": None}, "suji": {"qty": 500, "unit": "g", "days_left": None},
            "peas": {"qty": 250, "unit": "g", "days_left": None}, "paneer": {"qty": 400, "unit": "g", "days_left": 2},
            "atta": {"qty": 1000, "unit": "g", "days_left": None}, "tomato": {"qty": 4, "unit": "pcs", "days_left": 2}}
    ctx = PlanContext("2030-01-02", base, preferences={"diet": "vegetarian"})
    first = plan_day(["paneer_bhurji", "roti"], ctx)["breakfast"]
    other = plan_day(["paneer_bhurji", "roti"], ctx, avoid=set(first))["breakfast"]
    assert first and other and other != first
    only = {k: v for k, v in base.items() if k not in ("suji", "peas")}
    assert plan_day(["paneer_bhurji", "roti"], PlanContext("2030-01-02", only, preferences={"diet": "vegetarian"}),
                    avoid={"poha"})["breakfast"] == ["poha"]            # no alternative: repeat rather than skip




def test_cook_brief_always_lists_breakfast_lunch_and_dinner():
    from cooksmart import cookbrief, cookmsgs
    from cooksmart.providers.gnani import spoken_text
    lines = cookmsgs.meal_lines({"lunch": ["dal_tadka", "roti"]})
    assert len(lines) == 3 and lines[0].endswith("आज नहीं बनाना") and "दाल" in lines[1]
    assert lines[2].endswith("आज नहीं बनाना")
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    c.post("/api/h/owner/message", json={"text": "lunch dal tadka and roti"})          # only lunch named by the owner
    c.post("/api/h/owner/message", json={"text": "approve"})
    c.post("/api/h/trigger/morning")
    cook = [m["text"] for m in c.get("/api/h/cook/messages").json()][-1]
    assert cook.count("\n") >= 3 and "ब्रेकफास्ट:" in cook and "लंच:" in cook and "डिनर:" in cook
    assert "🌅" in cook
    assert "🌅" not in spoken_text(cook) and "\n" not in spoken_text(cook)             # the voice reads words, not icons


# ------------------------------------------------------------------ meal by meal: breakfast options, then lunch, then dinner
def _say(c, *texts):
    for t in texts:
        c.post("/api/h/owner/message", json={"text": t})


def _texts(c):
    return [m["text"] for m in c.get("/api/h/owner/messages").json() if not (m.get("payload") or {}).get("flow")]


def _flows(c):
    return [m["text"] for m in c.get("/api/h/owner/messages").json() if (m.get("payload") or {}).get("flow")]


def _plan(c):
    return c.get("/api/h/owner/state").json()["plan"]


def test_options_come_one_meal_at_a_time_breakfast_then_lunch_then_dinner():
    from cooksmart.recipes import RECIPES
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    first = _texts(c)[0]
    assert "What do you want for breakfast" in first and "What do you want for lunch" not in first and "What do you want for dinner" not in first
    p = _plan(c)
    assert p["stage"] == "breakfast" and p["proposals"]
    assert all(RECIPES[r]["course"] == "breakfast" for o in p["proposals"] for r in o["recipe_ids"])
    chosen_bf = p["proposals"][0]["recipe_ids"]
    _say(c, "1")                                                        # pick breakfast
    p = _plan(c)
    assert p["stage"] == "lunch" and p["meals"]["breakfast"] == chosen_bf
    assert "What do you want for lunch" in _texts(c)[-1] and "✅" in _texts(c)[-1] and "Breakfast" in _texts(c)[-1]
    assert not any(RECIPES[r]["course"] == "breakfast" for o in p["proposals"] for r in o["recipe_ids"])
    lunch = p["proposals"][1]["recipe_ids"]
    _say(c, "2")                                                        # pick lunch option 2
    p = _plan(c)
    assert p["stage"] == "dinner" and p["meals"]["lunch"] == lunch
    assert "What do you want for dinner" in _texts(c)[-1]
    assert all(not set(o["recipe_ids"]) & (set(chosen_bf) | set(lunch)) for o in p["proposals"])
    _say(c, "1")                                                        # pick dinner
    p = _plan(c)
    assert p["stage"] == "" and p["chosen"] and p["meals"]["dinner"]
    assert set(p["chosen"]) == set(chosen_bf) | set(lunch) | set(p["meals"]["dinner"])
    assert "Menu set" in " ".join(_texts(c)[-4:])


def test_each_meal_can_be_skipped_or_named_and_options_are_labelled():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    labels = [o["label"] for o in _plan(c)["proposals"]]
    assert all(labels) and len(set(labels)) == len(labels)
    _say(c, "skip")                                                     # no breakfast
    assert _plan(c)["meals"]["breakfast"] == [] and _plan(c)["stage"] == "lunch"
    _say(c, "dal tadka and roti")                                       # name lunch instead of tapping
    p = _plan(c)
    assert p["meals"]["lunch"] == ["dal_tadka", "roti"] and p["stage"] == "dinner"
    _say(c, "aloo gobi")                                                # name dinner
    p = _plan(c)
    assert p["meals"]["dinner"] == ["aloo_gobi"] and p["stage"] == ""


def test_naming_several_meals_at_once_jumps_ahead():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    _say(c, "breakfast upma, lunch dal tadka")
    p = _plan(c)
    assert p["meals"]["breakfast"] == ["upma"] and p["meals"]["lunch"] == ["dal_tadka"] and p["stage"] == "dinner"
    assert "What do you want for dinner" in _texts(c)[-1]
    _say(c, "dinner aloo gobi")
    assert _plan(c)["meals"]["dinner"] == ["aloo_gobi"] and _plan(c)["stage"] == ""


def test_named_meals_respect_allergies_at_every_stage():
    c = _day_env()
    _say(c, "Aarav is allergic to peanuts")
    c.post("/api/h/trigger/nightly_review")
    _say(c, "poha")                                                     # made with peanuts
    assert "won't plan" in _texts(c)[-1] and _plan(c)["stage"] == "breakfast" and _plan(c)["meals"] == {}


def test_silence_takes_option_one_for_every_remaining_meal_but_never_orders():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    _say(c, "1")                                                        # breakfast chosen, then the owner goes quiet
    c.post("/api/h/trigger/cutoff")
    p = _plan(c)
    assert p["stage"] == "" and p["reviewed"] is False and p["meals"]["lunch"] and p["meals"]["dinner"]
    assert c.get("/api/h/owner/state").json()["orders"] == []


def test_groceries_arrive_in_15_minutes_and_the_next_step_is_the_door():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    _say(c, "aloo gobi", "skip", "skip")                                # lunch named: cauliflower is short, so an order is needed
    _say(c, "approve")
    st = c.get("/api/h/owner/state").json()
    assert st["orders"] and all(o["eta_minutes"] == 15 for o in st["orders"])
    assert st["next"]["action"]["kind"] == "door"
    c.post("/api/h/door/arrive", json={"voice": "cook"})
    st = c.get("/api/h/owner/state").json()
    assert st["orders"][0]["status"] == "delivered" and "delivery" in [x["stage"] for x in st["story"]]


def test_day_story_fridge_decreases_through_meals_and_grows_on_delivery():
    c = _day_env()
    st = lambda: c.get("/api/h/owner/state").json()
    c.post("/api/h/trigger/nightly_review")
    _say(c, "1", "1", "1", "approve")
    assert [x["stage"] for x in st()["story"]][:2] == ["review", "plan"]
    c.post("/api/h/trigger/morning")
    shown = {i["name"]: i["shown"] for i in st()["fridge"]}
    for m in ("breakfast", "lunch", "dinner"):
        c.post(f"/api/h/trigger/serve_{m}")
    s2 = st()
    assert s2["served"] == ["breakfast", "lunch", "dinner"]
    after = {i["name"]: i["shown"] for i in s2["fridge"]}
    assert any(after.get(k, 0) < v for k, v in shown.items())
    assert any(d["qty"] < 0 for x in s2["story"] if x["stage"] == "lunch" for d in x["deltas"])
    c.post("/api/h/trigger/serve_lunch")
    assert st()["served"] == ["breakfast", "lunch", "dinner"]
    c.post("/api/h/trigger/end_of_day")
    c.post("/api/h/trigger/close_day")
    assert st()["story"][-1]["stage"] == "wrapup"


def test_stale_stock_still_gets_options_with_a_small_shop_for_each_meal():
    from cooksmart import repo as r
    app = create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:"))
    c = TestClient(app)
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/scenario/classic")
    r.update_household(app.state.db, "h", sim_date="2026-10-12")
    c.post("/api/h/trigger/nightly_review")
    first = _texts(c)[0]
    assert "Probably gone off by tomorrow" in first and "Not sure if you still have" in first
    assert "What do you want for breakfast" in first and first.count("🛒") >= 1


def test_every_path_that_re_asks_goes_step_by_step_never_a_whole_day_list():
    c = _day_env()
    c.post("/api/h/trigger/nightly_review")
    _say(c, "1", "1", "1")                                              # a finished menu
    _say(c, "change menu")
    last = _texts(c)[-1]
    assert "What do you want for breakfast" in last and "What do you want for lunch" not in last and "Tomorrow's plan" not in last
    _say(c, "something else")
    last = _texts(c)[-1]
    assert "What do you want for breakfast" in last and "Tomorrow's plan" not in last
    c2 = _day_env()
    c2.post("/api/mock/controls", json={"out_of_stock": ["cauliflower"]})
    c2.post("/api/h/trigger/nightly_review")
    _say(c2, "aloo gobi", "skip", "skip")                               # needs cauliflower, which no shop has
    texts = " ".join(_texts(c2))
    assert "Let's choose again" in texts and "Tomorrow's plan" not in texts


def test_breakfast_is_always_asked_even_when_no_option_can_be_made():
    from cooksmart import repo as r
    app = create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:"))
    c = TestClient(app)
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/scenario/empty_pantry")
    r.update_household(app.state.db, "h", sim_date="2026-10-20")          # everything is stale
    c.post("/api/h/trigger/nightly_review")
    last = _texts(c)[-1]
    assert "What do you want for breakfast?" in last and "skip" in last.lower()
    p = _plan(c)
    assert p["stage"] == "breakfast" and p["meals"] == {}                # still waiting for the owner, nothing skipped for them
    _say(c, "skip")
    assert _plan(c)["stage"] == "lunch" and "What do you want for lunch?" in _texts(c)[-1]


def test_the_day_flow_is_posted_whenever_the_state_changes_and_only_then():
    c = _day_env()
    assert _flows(c) == []
    c.post("/api/h/trigger/nightly_review")
    assert len(_flows(c)) == 1 and "Today's flow" in _flows(c)[0] and "choosing breakfast" in _flows(c)[0]
    _say(c, "help")                                                     # nothing changed in the day: no new flow
    assert len(_flows(c)) == 1
    _say(c, "1")                                                        # breakfast chosen: the day moved on
    assert len(_flows(c)) == 2 and "choosing lunch" in _flows(c)[-1] and "Breakfast:" in _flows(c)[-1]
    _say(c, "1", "1")                                                   # lunch, dinner -> menu set; one flow per action
    assert len(_flows(c)) == 4 and "✅ 9:10 PM Menu picked" in _flows(c)[-1]
    n = len(_flows(c))
    c.post("/api/h/trigger/morning")                                    # the cutoff + brief inside are one action, one flow
    assert len(_flows(c)) == n + 1 and "✅ 6:30 AM Cook briefed" in _flows(c)[-1]
    c.post("/api/h/trigger/serve_breakfast")
    assert len(_flows(c)) == n + 2 and "✅ 8:00 AM Breakfast" in _flows(c)[-1] and "👉" in _flows(c)[-1]
    # the flow is a pinned panel, never counted as a chat turn
    assert all((m.get("payload") or {}).get("flow") for m in c.get("/api/h/owner/messages").json() if m["text"].startswith("📅"))
