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
    first = env.plan()["proposals"][0]["recipe_ids"]
    env.agent.handle_owner(env.hid, "1")
    assert env.plan()["chosen"] == first


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
    assert msgs[0]["payload"] == {"voice": True} and msgs[1]["payload"] is None


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
