"""Agent Studio: editing the cook-call agent's prompt, knowledge base, FAQs and household profile."""
import io
import json
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from cooksmart import gnani_cli, gnani_prompt, repo, studio
from cooksmart.api import create_app
from cooksmart.config import Settings
from cooksmart.db import DB
from cooksmart.providers.gnani_platform import GnaniPlatform

PROMPT = gnani_prompt.load_prompt()


def client(**kw):
    platform = kw.pop("platform", None)
    s = Settings(":memory:", "", "m", "", "t", **kw)
    c = TestClient(create_app(s, DB(":memory:"), platform))
    c.post("/api/households", json={"id": "h"})
    return c


def detail(r):
    return r.json()["detail"]


# ------------------------------------------------------------------ reading
def test_studio_starts_on_defaults():
    st = client().get("/api/h/studio").json()
    assert st["prompt"]["current"] == PROMPT and not st["prompt"]["overridden"] and st["prompt"]["checks"]["errors"] == []
    assert len(st["docs"]) == 18 and not any(d["overridden"] for d in st["docs"])
    assert st["faqs"]["items"] and not st["faqs"]["overridden"]
    assert {v["name"] for v in st["prompt"]["variables"]} >= {"cautions_hi", "use_first_hi", "dishes_hi"}
    assert "peanut" in st["options"]["allergens"] and st["push"]["available"] is False


def test_unknown_household_is_404():
    assert client().get("/api/nope/studio").status_code == 404


# ------------------------------------------------------------------ the system prompt
def test_editing_the_prompt_is_saved_versioned_and_resettable():
    c = client()
    edited = PROMPT.replace('Address her as "{{ cook_name }}"', 'Address her as "{{ cook_name }} ji"')
    assert c.put("/api/h/studio/prompt", json={"content": edited}).json()["saved"] is True
    st = c.get("/api/h/studio").json()["prompt"]
    assert st["current"] == edited and st["overridden"] and len(st["history"]) == 1 and st["default"] == PROMPT
    c.delete("/api/h/studio/prompt")
    st = c.get("/api/h/studio").json()["prompt"]
    assert st["current"] == PROMPT and not st["overridden"] and len(st["history"]) == 1     # reset keeps the history


@pytest.mark.parametrize("bad,expect", [("", "empty"), ("hi {% if %}", "syntax"), ("hi {{ nonsense }}", "variable CookSmart doesn't send"),
                                        ("x" * 21000, "limit")], ids=["empty", "syntax", "unknown-variable", "too-long"])
def test_a_prompt_that_would_fail_on_a_live_call_is_refused(bad, expect):
    r = client().put("/api/h/studio/prompt", json={"content": bad})
    assert r.status_code == 422 and expect.lower() in " ".join(detail(r)["errors"]).lower()


def test_dropping_the_allergy_variable_needs_an_explicit_override():
    c = client()
    no_allergy = PROMPT.replace("{{ cautions_hi or \"none\" }}", "none")
    r = c.put("/api/h/studio/prompt", json={"content": no_allergy})
    assert r.status_code == 409 and detail(r)["needs_force"] and "allergy" in detail(r)["warnings"][0].lower()
    assert not c.get("/api/h/studio").json()["prompt"]["overridden"]
    ok = c.put("/api/h/studio/prompt", json={"content": no_allergy, "force": True})
    assert ok.json()["saved"] and any("allergy" in w.lower() for w in ok.json()["warnings"])


def test_preview_shows_what_the_agent_will_actually_receive():
    c = client()
    sample = c.post("/api/h/studio/prompt/preview", json={}).json()
    assert sample["using"] == "sample data" and "SAFETY" in sample["rendered"]
    c.post("/api/h/trigger/nightly_review"); c.post("/api/h/owner/message", json={"text": "dal tadka"})
    c.post("/api/h/owner/message", json={"text": "skip"}); c.post("/api/h/owner/message", json={"text": "skip"})        # breakfast, dinner
    live = c.post("/api/h/studio/prompt/preview", json={"call_type": "brief"}).json()
    assert live["using"] == "today's real plan" and "दाल तड़का" in live["rendered"] and live["variables"]["people"] == "4"
    unsaved = c.post("/api/h/studio/prompt/preview", json={"content": "Hello {{ cook_name }} / {{ dishes_hi }}"}).json()
    assert unsaved["rendered"].startswith("Hello ") and "दाल तड़का" in unsaved["rendered"]
    assert c.post("/api/h/studio/prompt/preview", json={"content": "{{ nope }}"}).status_code == 422
    assert c.post("/api/h/studio/prompt/preview", json={"call_type": "weird"}).status_code == 400


# ------------------------------------------------------------------ knowledge base
def test_editing_a_document_changes_the_kb_the_agent_is_given():
    c = client()
    name = "03_swaad_aur_pasand.md"
    r = c.put(f"/api/h/studio/docs/{name}", json={"content": "# घर का स्वाद\n\n- खाना कम तीखा रखें\n"})
    assert r.json()["saved"] is True
    st = {d["name"]: d for d in c.get("/api/h/studio").json()["docs"]}
    assert st[name]["overridden"] and st[name]["title"] == "घर का स्वाद" and st[name]["default"] != st[name]["content"]
    assert c.get("/api/h/gnani/kb").json()["files"][name].startswith("# घर का स्वाद")        # the viewer reflects the edit
    c.delete(f"/api/h/studio/docs/{name}")
    assert not {d["name"]: d for d in c.get("/api/h/studio").json()["docs"]}[name]["overridden"]


def test_documents_that_name_a_condition_are_flagged_not_hidden():
    c = client()
    r = c.put("/api/h/studio/docs/06_sehat.md", json={"content": "# सेहत\n\nपापा को diabetes है, चीनी कम दें\n"})
    assert r.json()["saved"] and "health condition" in r.json()["warnings"][0]
    d = {x["name"]: x for x in c.get("/api/h/studio").json()["docs"]}["06_sehat.md"]
    assert d["warnings"]                                                     # still flagged next time it's opened


def test_document_validation_and_unknown_names():
    c = client()
    assert c.put("/api/h/studio/docs/06_sehat.md", json={"content": "  "}).status_code == 422
    assert c.put("/api/h/studio/docs/06_sehat.md", json={"content": "x" * 31000}).status_code == 422
    assert c.put("/api/h/studio/docs/not_a_real_doc.md", json={"content": "x"}).status_code == 404


def test_custom_documents_can_be_added_and_removed():
    c = client()
    assert c.post("/api/h/studio/docs", json={"name": "Bad Name.txt", "content": "x"}).status_code == 422
    assert c.post("/api/h/studio/docs", json={"name": "custom_festivals.md", "content": "# त्योहार\n\nदिवाली पर पूरन पोली"}).json()["saved"]
    docs = {d["name"]: d for d in c.get("/api/h/studio").json()["docs"]}
    assert docs["custom_festivals.md"]["custom"] and len(docs) == 19
    assert "त्योहार" in c.get("/api/h/gnani/kb").json()["files"]["custom_festivals.md"]
    c.delete("/api/h/studio/docs/custom_festivals.md")
    assert "custom_festivals.md" not in {d["name"] for d in c.get("/api/h/studio").json()["docs"]}


def test_faqs_edit_validate_and_reset():
    c = client()
    good = [{"questions": ["क्या आरव मूंगफली खा सकता है?"], "answer": "नहीं, एलर्जी है."}]
    assert c.put("/api/h/studio/faqs", json={"faqs": good}).json()["saved"]
    st = c.get("/api/h/studio").json()["faqs"]
    assert st["items"] == good and st["overridden"]
    assert c.get("/api/h/gnani/kb").json()["faqs"] == good
    for bad in ([{"questions": [], "answer": "a"}], [{"questions": ["q"], "answer": ""}], [{"questions": ["q"] * 11, "answer": "a"}],
                [{"questions": ["q"], "answer": "a"}] * 101):
        assert c.put("/api/h/studio/faqs", json={"faqs": bad}).status_code == 422
    c.delete("/api/h/studio/faqs")
    assert not c.get("/api/h/studio").json()["faqs"]["overridden"]


def test_any_earlier_version_can_be_restored():
    c = client()
    for text in ("# एक\n\nपहला", "# दो\n\nदूसरा"):
        c.put("/api/h/studio/docs/09_naap_tol.md", json={"content": text})
    hist = {d["name"]: d for d in c.get("/api/h/studio").json()["docs"]}["09_naap_tol.md"]["history"]
    assert len(hist) == 2
    assert c.post("/api/h/studio/restore", json={"version_id": hist[-1]["id"]}).json()["restored"]
    now = {d["name"]: d for d in c.get("/api/h/studio").json()["docs"]}["09_naap_tol.md"]
    assert "पहला" in now["content"] and len(now["history"]) == 3
    assert c.post("/api/h/studio/restore", json={"version_id": 99999}).status_code == 404


def test_edits_are_per_household():
    c = client()
    c.post("/api/households", json={"id": "other"})
    c.put("/api/h/studio/prompt", json={"content": PROMPT + "\n# extra for h only"})
    c.put("/api/h/studio/docs/09_naap_tol.md", json={"content": "# केवल h\n\nx"})
    other = c.get("/api/other/studio").json()
    assert not other["prompt"]["overridden"] and not {d["name"]: d for d in other["docs"]}["09_naap_tol.md"]["overridden"]
    c.post(f"/api/other/studio/restore", json={"version_id": 1})        # h's version id: must not leak
    assert not c.get("/api/other/studio").json()["prompt"]["overridden"]


# ------------------------------------------------------------------ household profile
def test_profile_edit_feeds_planning_and_the_generated_kb():
    c = client()
    ok = c.put("/api/h/studio/profile", json={
        "family_size": 5, "diet": "vegetarian", "cook_name": "लता दीदी", "cook_phone": "+91 98000 00001",
        "members": [{"name": "मीरा", "age_group": "child", "allergies": ["egg"], "health": [], "notes": ["टिफ़िन सूखा"]}],
        "style": {"spice": "mild", "oil": "low"}, "customs": [{"weekday": "tuesday", "avoid": ["onion"], "text": "मंगलवार को प्याज़ नहीं"}],
        "kitchen": {"burners": 3, "cooker_litres": 5, "notes": ["मसाले ऊपर"]}, "units": {"katori_ml": 180}})
    assert ok.json()["saved"]
    p = c.get("/api/h/studio").json()["profile"]
    assert p["family_size"] == 5 and p["cook_name"] == "लता दीदी" and p["members"][0]["allergies"] == ["egg"]
    docs = {d["name"]: d["content"] for d in c.get("/api/h/studio").json()["docs"]}
    assert "मीरा" in docs["02_allergy_aur_suraksha.md"] and "180" in docs["09_naap_tol.md"] and "5 लोग" in docs["01_ghar_ka_parichay.md"]
    c.post("/api/h/trigger/nightly_review")
    assert not any("egg" in i for p_ in c.get("/api/h/owner/state").json()["plan"]["proposals"] for i in
                   [x for r in p_["recipe_ids"] for x in __import__("cooksmart.recipes", fromlist=["R"]).RECIPES[r]["needs"]])


@pytest.mark.parametrize("bad", [
    {"family_size": 0}, {"family_size": "abc"}, {"diet": "carnivore"}, {"cook_phone": "call me"},
    {"members": [{"name": "", "allergies": []}]}, {"members": [{"name": "x", "allergies": ["gravity"]}]},
    {"members": [{"name": "x", "health": ["flu"]}]}, {"members": [{"name": "x", "age_group": "alien"}]},
    {"members": [{"name": "x"}] * 13}, {"style": {"spice": "nuclear"}}, {"customs": [{"weekday": "funday"}]},
    {"units": {"katori_ml": 5}}, {"kitchen": {"burners": "many"}}])
def test_profile_validation_rejects_nonsense(bad):
    r = client().put("/api/h/studio/profile", json=bad)
    assert r.status_code == 422 and detail(r)["errors"]


# ------------------------------------------------------------------ export + push
def test_export_zip_contains_the_current_prompt_kb_and_faqs():
    c = client()
    c.put("/api/h/studio/docs/09_naap_tol.md", json={"content": "# नाप\n\nहमारा बदला हुआ"})
    c.put("/api/h/studio/prompt", json={"content": PROMPT + "\n# my edit"})
    r = c.get("/api/h/studio/export.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"prompt.j2", "kb/faqs.json", "UPLOAD.txt", "kb/01_ghar_ka_parichay.md", "kb/09_naap_tol.md"} <= names
    assert z.read("prompt.j2").decode().endswith("# my edit") and "हमारा बदला हुआ" in z.read("kb/09_naap_tol.md").decode()
    assert isinstance(json.loads(z.read("kb/faqs.json")), list)


def test_push_needs_keys_then_sends_the_current_prompt_to_gnani():
    assert client().post("/api/h/studio/prompt/push").status_code == 409
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"status": "success", "response": {}})

    plat = GnaniPlatform("K", client=httpx.Client(transport=httpx.MockTransport(handler)))
    c = client(platform=plat, inya_bot_id="BOT9")
    assert c.get("/api/h/studio").json()["push"]["available"] is True
    c.put("/api/h/studio/prompt", json={"content": PROMPT + "\n# pushed"})
    assert c.post("/api/h/studio/prompt/push").json()["pushed"] is True
    assert [s[:2] for s in seen] == [("POST", "/platform/v1/agents/prompt/validate"), ("PUT", "/platform/v1/agents/BOT9")]
    assert seen[1][2]["systemPrompt"].endswith("# pushed")


def test_a_gnani_rejection_is_reported_not_swallowed():
    plat = GnaniPlatform("K", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"message": "field systemPrompt is invalid"}))))
    c = client(platform=plat, inya_bot_id="BOT9")
    r = c.post("/api/h/studio/prompt/push")
    assert r.status_code == 502 and "systemPrompt" in detail(r)


def test_cli_kb_writes_the_edited_documents(tmp_path, monkeypatch):
    db_file = tmp_path / "x.db"
    monkeypatch.setenv("COOKSMART_DB", str(db_file))
    monkeypatch.chdir(tmp_path)
    db = DB(str(db_file))
    repo.create_household(db, "h", "H", "2026-10-01", preferences={"members": [{"name": "मीरा", "allergies": ["egg"]}]})
    studio.save(db, "h", "doc", "09_naap_tol.md", "# edited\n\nCLI sees this")
    out = tmp_path / "kb"
    assert gnani_cli.main(["kb", "--out", str(out), "--household", "h"]) == 0
    assert "CLI sees this" in (out / "09_naap_tol.md").read_text(encoding="utf-8")
    assert "मीरा" in (out / "02_allergy_aur_suraksha.md").read_text(encoding="utf-8")
