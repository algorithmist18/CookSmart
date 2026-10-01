from fastapi.testclient import TestClient

from cooksmart.api import create_app, parse_meta_payload
from cooksmart.config import Settings
from cooksmart.db import DB


def client():
    app = create_app(Settings(":memory:", "", "m", "", "tok"), DB(":memory:"))
    return TestClient(app)


def test_end_to_end_over_http():
    c = client()
    assert c.post("/api/households", json={"id": "h1"}).json()["created"]
    c.post("/api/h1/trigger/nightly_review")
    c.post("/api/h1/owner/message", json={"text": "palak dal"})
    c.post("/api/h1/trigger/morning")
    cook = c.get("/api/h1/cook/messages").json()
    assert cook and "पालक दाल" in cook[0]["text"]
    state = c.get("/api/h1/owner/state").json()
    assert state["plan"]["state"] == "briefed" and state["planner"] == "heuristic"
    assert c.post("/api/h1/trigger/bogus").status_code == 404
    assert c.get("/api/nope/owner/state").status_code == 404


def test_toggle_via_settings_and_text():
    c = client()
    c.post("/api/households", json={"id": "h1"})
    c.post("/api/h1/settings", json={"order_mode": "auto", "auto_cap": 300})
    h = c.get("/api/h1/owner/state").json()["household"]
    assert h["order_mode"] == "auto" and h["auto_cap"] == 300
    c.post("/api/h1/owner/message", json={"text": "mode approve"})
    assert c.get("/api/h1/owner/state").json()["household"]["order_mode"] == "approve"


def test_whatsapp_webhook_verify_and_routing():
    c = client()
    c.post("/api/households", json={"id": "h1", "owner_phone": "9111", "cook_phone": "9222"})
    assert c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "tok",
                                              "hub.challenge": "42"}).text == "42"
    assert c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "bad",
                                              "hub.challenge": "42"}).status_code == 403
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "9111", "type": "text", "text": {"body": "mode auto"}}]}}]}]}
    assert c.post("/webhook/whatsapp", json=body).json() == {"handled": 1}
    assert c.get("/api/h1/owner/state").json()["household"]["order_mode"] == "auto"
    assert list(parse_meta_payload({})) == []
