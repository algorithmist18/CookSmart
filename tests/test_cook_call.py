"""Household profile + allergies, the cook brief, the knowledge base, and the Gnani cook-call agent."""
import json
import re
import tempfile
from pathlib import Path

import httpx
import jinja2
import pytest
from fastapi.testclient import TestClient

from cooksmart import callresult, cookbrief, gnani_kb, gnani_prompt, inventory as inv, profile, repo, scenarios
from cooksmart.api import create_app
from cooksmart.config import Settings
from cooksmart.db import DB
from cooksmart.providers.gnani_platform import GnaniPlatform, PlatformError
from cooksmart.recipes import ALLERGENS, RECIPES

BANNED = ("₹", "rs.", "price", "quickcart", "freshbasket", "payment", "ऑर्डर", "पैसे", "रुपये", "otp", "delivery")
DEMO = json.loads(json.dumps(gnani_kb.DEMO_PROFILE))


def set_prefs(env, **kw):
    h = repo.get_household(env.db, env.hid)
    repo.update_household(env.db, env.hid, preferences={**h["preferences"], **kw})


def call_mode(env, phone="+919800000001"):
    set_prefs(env, cook_channel="call")
    repo.update_household(env.db, env.hid, cook_phone=phone)


def brief_for(env, **kw):
    return cookbrief.build(env.db, env.hid, repo.get_household(env.db, env.hid), env.plan(), **kw)


# ------------------------------------------------------------------ allergies are hard rules
def test_allergy_filters_every_option_and_blocks_a_requested_dish(env):
    set_prefs(env, members=[{"name": "Aarav", "age_group": "child", "allergies": ["peanut"]}])
    env.agent.nightly_review(env.hid)
    for p in env.plan()["proposals"]:
        assert not any("peanuts" in RECIPES[i]["needs"] for i in p["recipe_ids"])
    env.agent.handle_owner(env.hid, "poha")
    assert env.plan()["chosen"] == []                      # blocked, nothing chosen
    assert "won't plan" in env.owner()[-1] and "Aarav" in env.owner()[-1]
    assert any(a["event"] == "allergy_block" for a in repo.list_audit(env.db, env.hid))


def test_hidden_allergen_sources_are_covered(env):
    set_prefs(env, members=[{"name": "X", "allergies": ["chickpea", "gluten"]}])
    env.agent.nightly_review(env.hid)
    for rid in ("besan_chilla", "kadhi", "chole", "roti", "aloo_paratha"):
        env.agent.handle_owner(env.hid, rid.replace("_", " "))
        assert env.plan()["chosen"] == [], rid


def test_owner_can_record_allergies_by_chat_and_the_menu_is_replanned(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "Riya is allergic to milk and egg")
    members = repo.get_household(env.db, env.hid)["preferences"]["members"]
    assert members[0]["name"] == "Riya" and set(members[0]["allergies"]) == {"dairy", "egg"}
    for p in env.plan()["proposals"]:
        assert not any(set(RECIPES[i]["needs"]) & {"paneer", "curd", "milk", "cream", "egg"} for i in p["recipe_ids"])
    assert "Re-planned" in " ".join(env.owner())


def test_weekday_customs_are_honoured(env):
    set_prefs(env, customs=[{"weekday": "friday", "avoid": ["onion"], "text": "शुक्रवार को प्याज़ नहीं"}])  # DAY+1 is a Friday
    env.agent.nightly_review(env.hid)
    for p in env.plan()["proposals"]:
        assert not any("onion" in RECIPES[i]["needs"] for i in p["recipe_ids"])


def test_style_and_channel_commands(env):
    env.agent.handle_owner(env.hid, "spice mild")
    env.agent.handle_owner(env.hid, "less oil")
    env.agent.handle_owner(env.hid, "call the cook")
    prefs = repo.get_household(env.db, env.hid)["preferences"]
    assert prefs["style"] == {"spice": "mild", "oil": "low"} and prefs["cook_channel"] == "call"
    env.agent.handle_owner(env.hid, "message the cook")
    assert repo.get_household(env.db, env.hid)["preferences"]["cook_channel"] == "chat"


# ------------------------------------------------------------------ what the cook can't know
def test_brief_contains_inventory_expiry_taste_health_and_cautions(env):
    set_prefs(env, **DEMO)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak dal and roti")
    v = cookbrief.to_variables(brief_for(env))
    assert "पालक" in v["use_first_hi"] and "यूज़" in v["use_first_hi"]          # ageing item, with the reason
    assert "ग्राम" in v["ingredients_hi"] and v["people"] == "4"
    assert "मूंगफली" in v["cautions_hi"] and "आरव" in v["cautions_hi"]               # allergy said even though no peanut in the menu
    assert v["taste_tips_hi"] and v["health_note_hi"]
    assert "सुनीता" in v["cook_name"] or v["cook_name"] == "सुनीता दीदी"


def test_cook_never_sees_a_diagnosis_or_money(env):
    set_prefs(env, **DEMO)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "palak paneer")
    env.agent.handle_owner(env.hid, "approve")
    blob = json.dumps(cookbrief.to_variables(brief_for(env, order_coming=True)), ensure_ascii=False).lower()
    for w in BANNED + ("diabet", "मधुमेह", "high_bp", "bp", "cholesterol", "soft_food"):
        assert w not in blob, w
    assert "नमक कम" in blob and "चीनी" in blob                                          # ...but the instructions are there


@pytest.mark.parametrize("sc", [s.id for s in scenarios.SCENARIOS])
def test_brief_respects_the_boundary_in_every_scenario(env, sc):
    set_prefs(env, **DEMO)
    s = scenarios.load(env.db, env.controls, env.hid, sc)
    set_prefs(env, **{k: v for k, v in DEMO.items() if k in ("members", "style", "customs")})
    scenarios.play(env.agent, env.db, env.controls, env.hid, [st for st in s.script if st[0] != "cook"][:4])
    plan = env.plan()
    if not plan or not plan["chosen"]:
        pytest.skip("scenario ends without a chosen menu")
    blob = json.dumps(cookbrief.to_variables(brief_for(env, order_coming=plan["state"] == "ordered")), ensure_ascii=False).lower()
    for w in BANNED:
        assert w not in blob, (sc, w)


def test_template_syntax_is_stripped_from_variables_and_length_is_capped(env):
    b = cookbrief.CookBriefData("brief", "दीदी", 4, ["x"], owner_note="{{ evil }} {% if 1 %}hi{% endif %} " + "z" * 2000)
    v = cookbrief.to_variables(b)
    assert "{{" not in v["owner_note_hi"] and "{%" not in v["owner_note_hi"] and len(v["owner_note_hi"]) <= 700


# ------------------------------------------------------------------ the knowledge base
def test_knowledge_base_has_all_documents_and_keeps_diagnoses_out():
    docs = gnani_kb.build_docs(DEMO, 4)
    assert len(docs) == 9 and all(t.startswith("# ") for t in docs.values())
    blob = "".join(docs.values()).lower()
    for w in ("diabet", "मधुमेह", "high_bp", "gas_acidity", "cholesterol", "₹"):
        assert w not in blob, w
    assert "आरव" in docs["02_allergy_aur_suraksha.md"] and "मूंगफली" in docs["02_allergy_aur_suraksha.md"]
    assert "नमक कम" in docs["01_ghar_ka_parichay.md"]                     # a condition became an instruction
    assert "पालक" in docs["04_saaman_ki_dekhbhal.md"] and "टमाटर" in docs["05_swaad_ka_guide.md"]


def test_knowledge_base_is_per_household_and_never_leaks_across():
    a = gnani_kb.build_docs(DEMO, 4)["02_allergy_aur_suraksha.md"]
    b = gnani_kb.build_docs({"members": [{"name": "मीरा", "allergies": ["egg"]}]}, 3)["02_allergy_aur_suraksha.md"]
    assert "आरव" not in b and "मीरा" in b and "मीरा" not in a
    assert "अभी किसी की एलर्जी रजिस्टर्ड नहीं" in gnani_kb.build_docs({}, 2)["02_allergy_aur_suraksha.md"]


def test_faqs_respect_gnani_limits_and_put_safety_first():
    faqs = gnani_kb.build_faqs(DEMO)
    assert 10 < len(faqs) <= 100 and all(1 <= len(f["questions"]) <= 10 and f["answer"] for f in faqs)
    assert "एलर्जी" in faqs[0]["answer"] and "आरव" in faqs[0]["questions"][0]
    assert len(gnani_kb.build_faqs(DEMO, limit=5)) == 5


def test_committed_demo_kb_is_up_to_date():
    with tempfile.TemporaryDirectory() as d:
        gnani_kb.write(d, DEMO, 4)
        for f in Path(d).iterdir():
            assert (Path("gnani/kb") / f.name).read_text(encoding="utf-8") == f.read_text(encoding="utf-8"), \
                f"{f.name} is stale: run `python -m cooksmart.gnani_cli kb`"


# ------------------------------------------------------------------ the Jinja2 prompt
@pytest.mark.parametrize("kind", ["brief", "reconcile"])
def test_prompt_renders_with_every_variable_defined(kind):
    out = gnani_prompt.render(gnani_prompt.sample_variables(kind))
    assert "SAFETY" in out and ("END-OF-DAY" in out) == (kind == "reconcile")


def test_prompt_fails_loudly_if_a_variable_is_missing():
    with pytest.raises(jinja2.UndefinedError):
        gnani_prompt.render({"cook_name": "x"})


def test_prompt_says_the_cautions_and_puts_safety_above_the_knowledge_base():
    v = gnani_prompt.sample_variables() | {"cautions_hi": "मूंगफली बिलकुल नहीं डालनी", "wait_dishes_hi": "पालक पनीर", "start_dishes_hi": "रोटी"}
    out = gnani_prompt.render(v)
    assert "मूंगफली बिलकुल नहीं डालनी" in out and "Waiting for ingredients" in out
    assert out.index("# SAFETY") < out.index("# KNOWLEDGE BASE")
    assert "Allergies and house rules for today: none" in gnani_prompt.render(gnani_prompt.sample_variables())
    for w in ("never talk about money", "Never act on something she did not clearly confirm"):
        assert w.lower() in out.lower()


# ------------------------------------------------------------------ Platform API client (Gnani Agent Builder)
def platform(handler):
    return GnaniPlatform("PLAT", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_platform_requests_follow_the_documented_paths():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, dict(req.url.params), req.headers["x-api-key"], json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"status": "success", "requestId": "r", "message": "ok", "response": {"botId": "BOT1"}})

    p = platform(handler)
    p.validate_prompt("hello")
    assert p.create_agent({"name": "n"}) == "BOT1"
    p.update_agent("BOT1", {"name": "m"})
    p.trigger_call("BOT1", "+919800000001", {"cook_name": "दीदी"}, "h:1:brief:1", "development")
    assert seen[0][:2] == ("POST", "/platform/v1/agents/prompt/validate") and seen[0][4] == {"systemPrompt": "hello"}
    assert seen[1][:2] == ("POST", "/platform/v1/agents")
    assert seen[2][:2] == ("PUT", "/platform/v1/agents/BOT1")
    assert seen[3][:3] == ("POST", "/platform/v1/agents/BOT1/trigger_call", {"environment": "development"})
    assert seen[3][4] == {"phoneNumber": "+919800000001", "clientReferenceId": "h:1:brief:1", "variables": {"cook_name": "दीदी"}}
    assert all(s[3] == "PLAT" for s in seen)


@pytest.mark.parametrize("status,hint", [(400, "systemPrompt"), (401, "bad or missing key"), (403, "permission"), (429, "rate limited")])
def test_platform_errors_surface_gnanis_message(status, hint):
    p = platform(lambda r: httpx.Response(status, json={"message": "field systemPrompt is required"}))
    with pytest.raises(PlatformError) as e:
        p.validate_prompt("x")
    assert e.value.status == status and (hint in str(e.value))


def test_platform_network_failure_and_empty_key():
    def boom(req):
        raise httpx.ConnectError("down")
    with pytest.raises(PlatformError) as e:
        platform(boom).get_agent("B")
    assert e.value.status == 0
    with pytest.raises(ValueError):
        GnaniPlatform("")


# ------------------------------------------------------------------ the morning call
def test_morning_call_replaces_the_chat_brief(env):
    call_mode(env)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    placed = env.agent.caller.placed
    assert len(placed) == 1 and placed[0].call_type == "brief" and placed[0].phone == "+919800000001"
    assert "दाल तड़का" in placed[0].variables["dishes_hi"]
    assert env.cook() == []                                        # no chat brief: the call is the brief
    assert env.plan()["state"] == "briefed"
    assert "Calling the cook" in " ".join(env.owner())
    assert repo.list_calls(env.db, env.hid)[0]["status"] == "placed"


def test_failed_call_falls_back_to_the_chat_brief_so_the_cook_is_never_left_waiting(env):
    call_mode(env)
    env.agent.caller.fail_next = True
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    assert "दाल तड़का" in env.cook()[-1]
    assert any(a["event"] == "call_failed" for a in repo.list_audit(env.db, env.hid))
    assert repo.list_calls(env.db, env.hid)[0]["status"] == "failed"


def test_calls_are_off_by_default_and_for_chat_households(env):
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, "dal tadka")
    env.agent.morning_handoff(env.hid)
    assert env.agent.caller.placed == [] and env.cook()


def _briefed_by_call(env, dish="dal tadka"):
    call_mode(env)
    env.agent.nightly_review(env.hid)
    env.agent.handle_owner(env.hid, dish)
    env.agent.morning_handoff(env.hid)
    return repo.list_calls(env.db, env.hid)[0]["reference_id"]


def result(env, ref, kind, items=("paneer",)):
    call = repo.get_call(env.db, ref)
    return env.agent.handle_call_result(callresult.simulated_payload(kind, call, list(items)))


def test_only_confirmed_reports_change_stock(env):
    ref = _briefed_by_call(env)
    result(env, ref, "unconfirmed")
    assert inv.get(env.db, env.hid, "paneer")["qty"] == 200
    assert "Not applied" in " ".join(env.owner())
    ref2 = repo.add_call(env.db, env.hid, env.plan()["id"], "brief")["reference_id"]
    result(env, ref2, "item_finished")
    assert inv.get(env.db, env.hid, "paneer")["qty"] == 0


def test_webhook_is_idempotent(env):
    ref = _briefed_by_call(env)
    first = result(env, ref, "item_finished")
    second = result(env, ref, "item_finished")
    assert first["applied"] == 1 and second == {"ok": True, "duplicate": True}
    assert sum(a["event"] == "cook_update_applied" for a in repo.list_audit(env.db, env.hid)) == 1


def test_confirmed_gas_problem_on_the_call_switches_to_a_no_stove_meal(env):
    ref = _briefed_by_call(env)
    result(env, ref, "gas_problem")
    assert all(not RECIPES[i]["stove"] for i in env.plan()["chosen"])
    assert any(m["kind"] == "constraint" for m in repo.list_memory(env.db, env.hid))


def test_live_action_then_webhook_does_not_switch_twice(env):
    ref = _briefed_by_call(env)
    said = env.agent.live_cook_problem(env.hid, "stove")
    assert "बनाइए" in said
    chosen = env.plan()["chosen"]
    result(env, ref, "gas_problem")
    assert env.plan()["chosen"] == chosen
    assert sum(m["kind"] == "constraint" for m in repo.list_memory(env.db, env.hid)) == 1


def test_live_action_is_safe_when_there_is_nothing_to_switch(env):
    assert "पूछकर" in env.agent.live_cook_problem(env.hid, "stove")           # no plan yet
    _briefed_by_call(env)
    assert "पूछकर" in env.agent.live_cook_problem(env.hid, "teleport")        # unknown problem: never guess


def test_safety_issue_alerts_the_owner_urgently(env):
    ref = _briefed_by_call(env)
    result(env, ref, "safety")
    assert "safety issue" in env.owner()[-1] and "right now" in " ".join(env.owner())


def test_no_answer_falls_back_to_a_voice_note(env):
    ref = _briefed_by_call(env)
    assert result(env, ref, "no_answer")["fallback"] == "chat"
    assert "दाल तड़का" in env.cook()[-1]


def test_cook_on_leave_from_the_call(env):
    ref = _briefed_by_call(env)
    result(env, ref, "leave_tomorrow")
    assert repo.get_household(env.db, env.hid)["preferences"]["next"] == {"cook_off": True}


def test_unknown_call_is_ignored(env):
    assert env.agent.handle_call_result({"conversation_id": "nope", "client_reference_id": "x:1:brief:1"}) == \
        {"ok": False, "ignored": "unknown call"}


def test_evening_call_reconciles_stock_and_closes_the_day(env):
    _briefed_by_call(env)
    env.agent.end_of_day(env.hid)
    recon = [c for c in repo.list_calls(env.db, env.hid) if c["call_type"] == "reconcile"][0]
    assert env.agent.caller.placed[-1].variables["reconcile_items_hi"]
    result(env, recon["reference_id"], "reconcile", items=("dal", "onion"))
    assert inv.get(env.db, env.hid, "dal")["qty"] == 0 and inv.get(env.db, env.hid, "onion")["qty"] == 2
    assert env.plan()["state"] == "closed"


def test_call_payload_parsing_is_defensive():
    oc = callresult.parse_webhook({"conversationId": "c1", "clientReferenceId": "r1", "disposition_result": {"code": "RNR"},
                                   "post_call_extraction_v2": {"data": {"acknowledged": "yes", "reports": [
                                       {"type": "used_up", "item": "paneer", "confirmed": "true"},
                                       {"type": "used_up", "item": "unobtainium", "confirmed": True},
                                       {"type": "remaining", "item": "onion", "confirmed": True}]}}})
    assert oc.no_answer and oc.acknowledged and oc.conversation_id == "c1" and oc.reference_id == "r1"
    assert [r["item"] for r in oc.reports] == ["paneer"] and len(oc.ignored) == 2        # bad item and quantity-less "remaining"


# ------------------------------------------------------------------ HTTP: webhook, live action, dynamic message
def app(token="tok"):
    s = Settings(":memory:", "", "m", "", "t", gnani_webhook_token=token)
    return TestClient(create_app(s, DB(":memory:")))


def start(c):
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/settings", json={"cook_channel": "call", "cook_phone": "+919800000001"})
    c.post("/api/h/trigger/nightly_review"); c.post("/api/h/owner/message", json={"text": "dal tadka"})
    c.post("/api/h/trigger/morning")
    return c.get("/api/h/owner/state").json()["calls"][0]["reference_id"]


def test_gnani_endpoints_are_off_without_a_token_and_locked_with_one():
    off = app(token="")
    assert off.post("/gnani/webhook/call-ended", json={}).status_code == 503
    c = app()
    assert c.post("/gnani/webhook/call-ended", json={}).status_code == 401
    assert c.post("/gnani/webhook/call-ended?token=wrong", json={}).status_code == 401
    assert c.post("/gnani/action/h/cook-problem?token=wrong", json={}).status_code == 401
    assert c.post("/gnani/dynamic/h/brief").status_code == 401
    assert c.post("/gnani/webhook/call-ended?token=tok", content=b"not json").status_code == 400


def test_webhook_over_http_applies_confirmed_items_only():
    c = app(); ref = start(c)
    body = callresult.simulated_payload("item_finished", {"reference_id": ref}, ["paneer"])
    assert c.post("/gnani/webhook/call-ended?token=tok", json=body).json()["applied"] == 1
    assert c.post("/gnani/webhook/call-ended?token=tok", json=body).json()["duplicate"] is True
    inv_ = {i["name"]: i for i in c.get("/api/h/owner/state").json()["inventory"]}
    assert inv_["paneer"]["qty"] == 0
    state = c.get("/api/h/owner/state").json()
    assert state["calls"][0]["status"] == "processed" and state["call_provider"]["live"] is False


def test_live_action_returns_the_documented_dynamic_message_shape():
    c = app(); start(c)
    r = c.post("/gnani/action/h/cook-problem?token=tok", json={"arguments": {"problem": "stove"}}).json()
    text = r["additional_info"]["inya_data"]["text"]
    assert text == r["text"] and "बनाइए" in text
    assert c.post("/gnani/action/nope/cook-problem?token=tok", json={}).status_code == 404


def test_dynamic_brief_is_always_fresh():
    c = app(); start(c)
    first = c.post("/gnani/dynamic/h/brief?token=tok").json()["additional_info"]["inya_data"]
    assert "दाल तड़का" in first["text"] and first["user_context"]["people"] == "4"
    c.post("/api/h/owner/message", json={"text": "family of 6"})
    again = c.post("/gnani/dynamic/h/brief?token=tok").json()["additional_info"]["inya_data"]
    assert again["user_context"]["people"] == "6"


def test_simulator_endpoint_runs_the_real_handler_and_is_household_scoped():
    c = app(); ref = start(c)
    assert c.post(f"/api/h/calls/{ref}/simulate", json={"kind": "gas_problem"}).json()["ok"] is True
    c.post("/api/households", json={"id": "other"})
    assert c.post(f"/api/other/calls/{ref}/simulate", json={"kind": "gas_problem"}).status_code == 404


def test_cook_channel_and_phone_settings():
    c = app(); c.post("/api/households", json={"id": "h"})
    c.post("/api/h/settings", json={"cook_channel": "call", "cook_phone": " +919800000001 "})
    h = c.get("/api/h/owner/state").json()["household"]
    assert h["preferences"]["cook_channel"] == "call" and h["cook_phone"] == "+919800000001"
    c.post("/api/h/settings", json={"cook_phone": ""})
    assert c.get("/api/h/owner/state").json()["household"]["cook_phone"] is None


def test_loading_a_scenario_clears_old_call_records(env):
    ref = _briefed_by_call(env)
    assert repo.list_calls(env.db, env.hid)
    scenarios.load(env.db, env.controls, env.hid, "classic")
    assert repo.list_calls(env.db, env.hid) == [] and repo.get_call(env.db, ref) is None


@pytest.mark.parametrize("sid", ["allergy_family", "morning_call", "call_gas_problem", "call_unanswered", "call_unconfirmed"])
def test_new_scenarios_end_in_the_story_they_promise(env, sid):
    sc = scenarios.load(env.db, env.controls, env.hid, sid)
    scenarios.play(env.agent, env.db, env.controls, env.hid, sc.script)
    owner = " ".join(env.owner())
    if sid == "allergy_family":
        assert "won't plan" in owner and env.plan()["chosen"]
        assert not any("peanuts" in RECIPES[i]["needs"] for i in env.plan()["chosen"])
    if sid == "morning_call":
        assert env.cook() == [] and env.plan()["state"] == "closed"
    if sid == "call_gas_problem":
        assert all(not RECIPES[i]["stove"] for i in env.plan()["chosen"])
    if sid == "call_unanswered":
        assert env.cook() and "दाल तड़का" in env.cook()[-1]
    if sid == "call_unconfirmed":
        assert "Not applied" in owner and inv.get(env.db, env.hid, "dal")["qty"] == 500


def test_english_edition_mirrors_every_hindi_document_and_stays_cook_safe():
    hi, en_ = gnani_kb.build_docs(DEMO, 4), gnani_kb.build_docs_en(DEMO, 4)
    assert len(en_) == len(hi) == 9 and all(n.startswith("en_") for n in en_) and all(t.startswith("# ") for t in en_.values())
    assert [n[3:5] for n in en_] == [n[:2] for n in hi]                       # same nine topics, same order
    blob = "".join(en_.values()).lower()
    for w in ("diabet", "high_bp", "gas_acidity", "cholesterol", "₹", "otp"):
        assert w not in blob, w
    allergy = en_["en_02_allergy_and_safety.md"]
    assert "आरव" in allergy and "Peanuts" in allergy and "112" in allergy
    assert "Spice: mild" in en_["en_01_household_profile.md"]
    assert "आरव" not in gnani_kb.build_docs_en({"members": [{"name": "Meera", "allergies": ["egg"]}]}, 3)["en_02_allergy_and_safety.md"]
    assert "No allergies registered" in gnani_kb.build_docs_en({}, 2)["en_02_allergy_and_safety.md"]
    mild = en_["en_01_household_profile.md"].count("ild spice")
    assert mild <= 3                                                          # a clause is said once per person, whatever its case


def test_english_faqs_are_in_the_set_safety_first_within_the_limit():
    faqs = gnani_kb.build_all_faqs(DEMO)
    assert len(faqs) <= 100
    qs = " ".join(q for f in faqs for q in f["questions"])
    assert "Can I give आरव peanuts?" in qs and "I can smell gas" in qs and "गैस की स्मेल आ रही है" in qs
    assert all(1 <= len(f["questions"]) <= 10 and f["answer"] for f in faqs)
    assert any("allerg" in f["answer"].lower() or "एलर्जी" in f["answer"] for f in faqs[:6])
