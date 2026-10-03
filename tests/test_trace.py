"""The activity panel's data: inputs, calls to Gnani (and what came back), and messages sent to people."""
import json

import httpx
from fastapi.testclient import TestClient

from cooksmart import trace
from cooksmart.api import create_app
from cooksmart.config import Settings
from cooksmart.db import DB
from cooksmart.providers.gnani import GnaniSpeechProvider
from cooksmart.providers.gnani_platform import GnaniPlatform


def client():
    c = TestClient(create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:")))
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/scenario/classic")
    return c


def rows(c, **q):
    return c.get("/api/h/trace", params=q).json()


def test_inputs_messages_and_mock_gnani_calls_are_all_recorded_in_order():
    c = client()
    c.post("/api/h/settings", json={"cook_channel": "call", "cook_phone": "+919800000001"})
    c.post("/api/h/trigger/nightly_review")
    c.post("/api/h/owner/message", json={"text": "skip"})
    c.post("/api/h/cook/message", json={"text": "namaste", "voice": True})
    t = rows(c)
    kinds = [(r["kind"], r["label"]) for r in t]
    assert ("input", "Button: nightly review") in kinds and ("input", "Owner message") in kinds
    assert ("message", "To owner") in kinds and ("input", "Cook message (voice note)") in kinds
    assert ("message", "To cook (voice note)") in kinds
    assert any(k == "gnani" and "TTS" in l for k, l in kinds)                     # every voice note goes through (mock) TTS
    assert [r["id"] for r in t] == sorted(r["id"] for r in t)
    first = next(r for r in t if r["label"] == "Owner message")
    assert first["request"] == {"text": "skip"}
    assert "What do you want for lunch" in next(r for r in t if r["kind"] == "message" and "lunch" in json.dumps(r["request"]))["request"]["text"]


def test_a_call_to_the_cook_shows_the_trigger_call_request_with_variables():
    c = client()
    c.post("/api/h/settings", json={"cook_channel": "call", "cook_phone": "+919800000001"})
    c.post("/api/h/trigger/nightly_review")
    c.post("/api/h/owner/message", json={"text": "dal tadka"})
    c.post("/api/h/owner/message", json={"text": "skip"})
    c.post("/api/h/owner/message", json={"text": "skip"})
    c.post("/api/h/trigger/morning")
    call = next(r for r in rows(c) if r["kind"] == "gnani" and "trigger_call" in r["label"])
    assert call["request"]["phoneNumber"] == "+919800000001" and "clientReferenceId" in call["request"]
    assert "dishes_hi" in call["request"]["variables"] and call["response"]["status"] == "mock"


def test_polling_returns_only_new_rows_and_households_are_separate():
    c = client()
    c.post("/api/h/trigger/nightly_review")
    last = rows(c)[-1]["id"]
    assert rows(c, after=last) == []
    c.post("/api/h/owner/message", json={"text": "help"})
    assert [r["label"] for r in rows(c, after=last)][:1] == ["Owner message"]
    c.post("/api/households", json={"id": "other"})
    assert c.get("/api/other/trace").json() == []


def test_real_gnani_calls_show_request_and_response_but_never_the_key_or_raw_audio():
    seen = []
    trace.set_sink(lambda **row: seen.append(row))
    trace.bind("h")

    def handler(req: httpx.Request) -> httpx.Response:
        if "stt" in str(req.url):
            return httpx.Response(200, json={"transcript": "paneer khatam", "confidence": 0.9})
        return httpx.Response(200, content=b"RIFF....audio", headers={"content-type": "audio/wav"})
    sp = GnaniSpeechProvider("SECRET-KEY-123", stt_url="https://x/stt", tts_url="https://x/tts", client=httpx.Client(transport=httpx.MockTransport(handler)))
    sp.transcribe_audio(b"\x00" * 5000, "audio/wav", "hi-IN")
    sp.synthesize("नमस्ते", "hi-IN")
    plat = GnaniPlatform("PLATFORM-KEY-9", client=httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"status": "success", "response": {"conversationId": "c1"}}))))
    plat.trigger_call("bot1", "+919800000001", {"dishes_hi": "x"}, "ref-1")
    stt, tts, call = seen
    assert stt["label"] == "Gnani STT (speech to text)" and stt["request"]["audio_file"] == "<5000 bytes>"
    assert "paneer khatam" in stt["response"]["body"]
    assert tts["request"]["body"]["text"] == "नमस्ते" and "bytes of audio" in tts["response"]["body"]
    assert call["request"]["body"]["clientReferenceId"] == "ref-1" and call["response"]["body"]["response"]["conversationId"] == "c1"
    blob = json.dumps(seen, ensure_ascii=False)
    assert "SECRET-KEY-123" not in blob and "PLATFORM-KEY-9" not in blob
    trace.set_sink(None)


def test_gnani_errors_are_logged_as_errors():
    seen = []
    trace.set_sink(lambda **row: seen.append(row))
    trace.bind("h")
    plat = GnaniPlatform("K", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "bad key"}))))
    try:
        plat.trigger_call("bot1", "+91", {}, "r")
    except Exception:
        pass
    assert seen[0]["status"] == "error" and seen[0]["response"]["status"] == 401
    trace.set_sink(None)


def test_redaction_and_a_reset_clears_the_log():
    assert trace.redact({"api_key": "abc", "ok": 1, "audio": b"xx"}) == {"api_key": "***", "ok": 1, "audio": "<2 bytes>"}
    c = client()
    c.post("/api/h/trigger/nightly_review")
    assert rows(c)
    c.post("/api/h/reset")
    assert rows(c) == []


def test_the_activity_panel_is_closed_by_default_and_does_not_clutter_the_page():
    html = TestClient(create_app(Settings(":memory:", "", "m", "", "t"), DB(":memory:"))).get("/").text
    assert '<aside id="trace" hidden' in html and 'id="traceBtn"' in html
