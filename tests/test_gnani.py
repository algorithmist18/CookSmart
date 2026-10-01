"""Gnani speech: request shapes follow Gnani's published curl examples; responses are parsed defensively."""
import base64
import json
import socket
import struct
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

from cooksmart import repo
from cooksmart.api import build_speech, create_app
from cooksmart.config import Settings
from cooksmart.db import DB
from cooksmart.providers.controls import MockControls
from cooksmart.providers.gnani import GnaniSpeechProvider, kitchen_vocabulary
from cooksmart.providers.speech import MockSpeechProvider, ResilientSpeech, SpeechError


def wav(seconds=1.0, rate=16000):
    n = int(seconds * rate)
    pcm = b"\x00\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def provider(handler, **kw):
    return GnaniSpeechProvider("KEY123", client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


# ------------------------------------------------------------------ STT request shape
def test_stt_request_matches_the_published_contract():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["headers"], seen["body"] = str(req.url), req.headers, req.read()
        return httpx.Response(200, json={"transcript": "पनीर खत्म"})

    tr = provider(handler).transcribe_audio(wav(), "audio/wav", "hi-IN")
    assert seen["url"] == "https://api.vachana.ai/stt/v3"
    assert seen["headers"]["x-api-key-id"] == "KEY123"
    assert seen["headers"]["content-type"].startswith("multipart/form-data")
    body = seen["body"]
    for field in (b'name="audio_file"', b'name="language_code"', b'name="format"', b'name="bias_list"',
                  b'name="bias_score"', b'name="itn_native_numerals"'):
        assert field in body, field
    assert b"hi-IN" in body and b"transcribe" in body and b"RIFF" in body
    bias = json.loads(body.split(b'name="bias_list"')[1].split(b"\r\n\r\n", 1)[1].split(b"\r\n--", 1)[0])
    assert "पनीर" in bias and "paneer" in bias and "टमाटर" in bias
    assert (tr.text, tr.source) == ("पनीर खत्म", "gnani") and tr.confidence >= 0.6


def test_kitchen_vocabulary_has_hindi_and_hinglish_ingredient_names():
    v = kitchen_vocabulary()
    assert {"पनीर", "paneer", "tamatar", "खत्म"} <= set(v) and len(v) == len(set(v))


@pytest.mark.parametrize("body,text", [
    ({"transcript": "आलू खत्म"}, "आलू खत्म"),
    ({"text": "आलू खत्म", "confidence": 0.77}, "आलू खत्म"),
    ({"data": {"transcript": "आलू खत्म"}}, "आलू खत्म"),
    ({"result": [{"text": "आलू"}, {"text": "खत्म"}]}, "आलू खत्म"),
    ("आलू खत्म", "आलू खत्म"),
])
def test_stt_response_shapes_are_tolerated(body, text):
    def handler(req):
        return httpx.Response(200, json=body)
    tr = provider(handler).transcribe_audio(wav(), "audio/wav", "hi-IN")
    assert tr.text == text and tr.error is None


def test_stt_confidence_is_used_when_the_service_provides_it():
    tr = provider(lambda r: httpx.Response(200, json={"text": "x", "confidence": 0.42})).transcribe_audio(wav(), "audio/wav", "hi-IN")
    assert tr.confidence == 0.42


def test_unrecognised_stt_response_is_kept_for_debugging_and_never_acted_on():
    tr = provider(lambda r: httpx.Response(200, json={"weird": 1})).transcribe_audio(wav(), "audio/wav", "hi-IN")
    assert tr.text == "" and tr.confidence == 0 and "weird" in tr.raw and tr.error


def test_empty_transcript_means_zero_confidence():
    tr = provider(lambda r: httpx.Response(200, json={"transcript": "  "})).transcribe_audio(wav(), "audio/wav", "hi-IN")
    assert tr.confidence == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_errors_raise_speech_error(status):
    with pytest.raises(SpeechError):
        provider(lambda r: httpx.Response(status, text="nope")).transcribe_audio(wav(), "audio/wav", "hi-IN")


def test_oversized_audio_is_refused_before_upload():
    called = []
    with pytest.raises(SpeechError):
        provider(lambda r: called.append(1) or httpx.Response(200, json={})).transcribe_audio(b"0" * 3_000_000, "audio/wav", "hi-IN")
    assert not called


# ------------------------------------------------------------------ fallback behaviour
def test_resilient_speech_falls_back_to_browser_hint_and_records_the_error():
    s = ResilientSpeech(provider(lambda r: httpx.Response(401, text="bad key")), MockSpeechProvider(), MockControls())
    tr = s.transcribe_audio(wav(), "audio/wav", "hi-IN", hint="पनीर खत्म")
    assert tr.text == "पनीर खत्म" and tr.source == "browser" and "SpeechError" in tr.error
    none = s.transcribe_audio(wav(), "audio/wav", "hi-IN")            # no hint: honest "unclear"
    assert none.text == "" and none.confidence == 0


def test_unclear_voice_switch_degrades_even_the_real_provider():
    c = MockControls(); c.stt_low_confidence = True
    s = ResilientSpeech(provider(lambda r: httpx.Response(200, json={"transcript": "ठीक"})), MockSpeechProvider(), c)
    assert s.transcribe_audio(wav(), "audio/wav", "hi-IN").confidence <= 0.35


# ------------------------------------------------------------------ TTS
def test_tts_request_matches_the_published_contract_and_accepts_raw_wav():
    seen = {}

    def handler(req):
        seen["url"], seen["headers"], seen["json"] = str(req.url), req.headers, json.loads(req.read())
        return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav"})

    note = provider(handler).synthesize("नमस्ते, आप कैसे हैं?", "hi-IN")
    assert seen["url"] == "https://api.vachana.ai/api/v1/tts/inference"
    assert seen["headers"]["x-api-key-id"] == "KEY123"
    assert seen["json"] == {"text": "नमस्ते, आप कैसे हैं?", "voice": "Nalini", "model": "timbre-v2.5", "language": "hi-IN",
                            "speed": 1, "audio_config": {"encoding": "linear_pcm", "container": "wav", "num_channels": 1,
                                                         "sample_rate": 48000, "sample_width": 2}}
    assert note.audio[:4] == b"RIFF" and note.mime == "audio/wav"


def test_tts_accepts_json_with_base64_audio():
    b64 = base64.b64encode(wav()).decode()
    note = provider(lambda r: httpx.Response(200, json={"audioContent": b64})).synthesize("हाँ", "hi-IN")
    assert note.audio[:4] == b"RIFF"
    note = provider(lambda r: httpx.Response(200, json={"data": {"audio": b64}})).synthesize("हाँ", "hi-IN")
    assert note.audio[:4] == b"RIFF"


def test_tts_is_cached_so_repeated_messages_cost_nothing():
    calls = []
    p = provider(lambda r: calls.append(1) or httpx.Response(200, content=wav(), headers={"content-type": "audio/wav"}))
    a, b = p.synthesize("नमस्ते", "hi-IN"), p.synthesize("नमस्ते", "hi-IN")
    p.synthesize("धन्यवाद", "hi-IN")
    assert a is b and len(calls) == 2


def test_tts_errors_raise_and_unknown_shapes_raise():
    with pytest.raises(SpeechError):
        provider(lambda r: httpx.Response(500, text="x")).synthesize("हाँ", "hi-IN")
    with pytest.raises(SpeechError):
        provider(lambda r: httpx.Response(200, json={"nothing": "here"})).synthesize("हाँ", "hi-IN")


# ------------------------------------------------------------------ provider selection
def settings(**kw):
    base = dict(db_path=":memory:", anthropic_api_key="", model="m", gnani_api_key="", whatsapp_verify_token="t")
    return Settings(**{**base, **kw})


def test_provider_selection():
    c = MockControls()
    assert isinstance(build_speech(settings(), c), MockSpeechProvider)                       # no key: offline
    assert isinstance(build_speech(settings(gnani_api_key="k"), c), ResilientSpeech)          # key: Gnani
    assert isinstance(build_speech(settings(gnani_api_key="k", speech="mock"), c), MockSpeechProvider)
    with pytest.raises(RuntimeError):
        build_speech(settings(speech="gnani"), c)


# ------------------------------------------------------------------ end to end over real HTTP
@pytest.fixture
def fake_gnani():
    """A local stand-in for api.vachana.ai that follows the published contract."""
    seen = {"stt": [], "tts": []}
    app = FastAPI()

    @app.post("/stt/v3")
    async def stt(request: Request):
        if request.headers.get("x-api-key-id") != "GOOD":
            return JSONResponse({"error": "unauthorised"}, status_code=401)
        body = await request.body()
        seen["stt"].append(body)
        said = "पनीर खत्म हो गया" if b"RIFF" in body else ""
        return {"transcript": said}

    @app.post("/api/v1/tts/inference")
    async def tts(request: Request):
        seen["tts"].append(await request.json())
        return Response(wav(0.2), media_type="audio/wav")

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True); t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", seen
    server.should_exit = True; t.join(timeout=3)


def app_with(base, key):
    return create_app(settings(gnani_api_key=key, gnani_stt_url=f"{base}/stt/v3",
                               gnani_tts_url=f"{base}/api/v1/tts/inference"), DB(":memory:"))


def test_recorded_voice_note_is_transcribed_read_back_and_answered_with_a_gnani_voice_note(fake_gnani):
    base, seen = fake_gnani
    c = TestClient(app_with(base, "GOOD"))
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/trigger/nightly_review"); c.post("/api/h/owner/message", json={"text": "dal tadka"})
    c.post("/api/h/trigger/morning")

    r = c.post("/api/h/cook/voice", content=wav(), headers={"content-type": "audio/wav"})
    assert r.json() == {"ok": True}
    assert b'name="language_code"' in seen["stt"][0] and b"hi-IN" in seen["stt"][0]
    msgs = c.get("/api/h/cook/messages").json()
    heard = [m for m in msgs if m["sender"] == "user"][-1]
    assert heard["text"] == "पनीर खत्म हो गया" and heard["payload"]["stt"] == "gnani"
    # read back before acting, as a Gnani-synthesised voice note
    reply = msgs[-1]
    assert "सही है?" in reply["text"] and reply["payload"]["media"]
    audio = c.get(f"/api/h/media/{reply['payload']['media']}")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF" and audio.headers["content-type"] == "audio/wav"
    assert seen["tts"][-1]["voice"] == "Nalini" and seen["tts"][-1]["language"] == "hi-IN"
    assert c.get("/api/h/owner/state").json()["speech"]["live"] is True
    # stock is untouched until she says haan
    paneer = [i for i in c.get("/api/h/owner/state").json()["inventory"] if i["name"] == "paneer"][0]
    assert paneer["qty"] == 200
    c.post("/api/h/cook/message", json={"text": "haan"})
    paneer = [i for i in c.get("/api/h/owner/state").json()["inventory"] if i["name"] == "paneer"][0]
    assert paneer["qty"] == 0


def test_bad_key_falls_back_cleanly_and_is_visible_in_the_audit_log(fake_gnani):
    base, _ = fake_gnani
    c = TestClient(app_with(base, "WRONG"))
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/trigger/nightly_review"); c.post("/api/h/owner/message", json={"text": "dal tadka"})
    c.post("/api/h/trigger/morning")
    c.post("/api/h/cook/voice", content=wav(), headers={"content-type": "audio/wav"})     # no hint available
    last = c.get("/api/h/cook/messages").json()[-1]
    assert "आवाज़ साफ़ नहीं आई" in last["text"]
    stt = [a for a in c.get("/api/h/owner/state").json()["audit"] if a["event"] == "stt"][0]
    assert "rejected the API key" in stt["detail"]["error"]
    c.post("/api/h/cook/voice", content=wav(), headers={"content-type": "audio/wav", "x-transcript-hint": "%E0%A4%B9%E0%A4%BE%E0%A4%81"})
    heard = [m for m in c.get("/api/h/cook/messages").json() if m["sender"] == "user"][-1]
    assert heard["payload"]["stt"] == "browser"


def test_voice_endpoint_validates_input():
    c = TestClient(create_app(settings(), DB(":memory:")))
    c.post("/api/households", json={"id": "h"})
    assert c.post("/api/h/cook/voice", content=b"").status_code == 400
    assert c.post("/api/h/cook/voice", content=b"0" * 2_600_000).status_code == 413
    assert c.post("/api/nope/cook/voice", content=b"x").status_code == 404
    assert c.get("/api/h/media/999").status_code == 404


def test_media_is_scoped_to_its_household(fake_gnani):
    base, _ = fake_gnani
    c = TestClient(app_with(base, "GOOD"))
    c.post("/api/households", json={"id": "a"}); c.post("/api/households", json={"id": "b"})
    c.post("/api/a/trigger/nightly_review"); c.post("/api/a/owner/message", json={"text": "dal tadka"})
    c.post("/api/a/trigger/morning")
    mid = [m for m in c.get("/api/a/cook/messages").json() if m["payload"] and m["payload"].get("media")][0]["payload"]["media"]
    assert c.get(f"/api/a/media/{mid}").status_code == 200
    assert c.get(f"/api/b/media/{mid}").status_code == 404


def test_mock_mode_records_audio_without_a_transcript_as_unclear():
    c = TestClient(create_app(settings(), DB(":memory:")))
    c.post("/api/households", json={"id": "h"})
    c.post("/api/h/cook/voice", content=wav(), headers={"content-type": "audio/wav"})
    assert "आवाज़ साफ़ नहीं आई" in c.get("/api/h/cook/messages").json()[-1]["text"]
    assert c.get("/api/h/owner/state").json()["speech"]["live"] is False
