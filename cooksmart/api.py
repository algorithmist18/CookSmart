"""FastAPI app: mock WhatsApp UI endpoints, trigger endpoints (what the scheduler will call), and a
Meta-format WhatsApp webhook so the real channel can be swapped in later."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import inventory as inv
from . import repo
from .agent import Agent
from .channels import MockChannel
from .config import Settings, get_settings
from .db import DB
from .nlu import NLU, ClaudeNLU
from .planner import ClaudePlanner, Planner
from .providers.controls import MockControls
from .providers.dispatch import MockDispatchProvider
from .providers.grocery import MockGroceryProvider
from .providers.payment import MockPaymentProvider
from .providers.speech import MockSpeechProvider
from .providers.voice import MockVoiceVerifier

STATIC = Path(__file__).parent / "static"


def build_agent(settings: Settings, db: DB, controls: MockControls) -> Agent:
    claude_planner = claude_nlu = None
    if settings.anthropic_api_key:
        claude_planner = ClaudePlanner(settings.anthropic_api_key, settings.model)
        claude_nlu = ClaudeNLU(settings.anthropic_api_key, settings.model)
    return Agent(db, MockChannel(db), Planner(claude_planner), NLU(claude_nlu), MockSpeechProvider(controls),
                 MockGroceryProvider(controls), MockDispatchProvider(), MockPaymentProvider(controls),
                 MockVoiceVerifier())


class TextBody(BaseModel):
    text: str
    voice: bool = True


class SettingsBody(BaseModel):
    order_mode: str | None = None
    auto_cap: int | None = None


class HouseholdBody(BaseModel):
    id: str = "demo"
    name: str = "Demo Household"
    seed: bool = True
    owner_phone: str | None = None
    cook_phone: str | None = None


class DoorBody(BaseModel):
    voice: str = "cook"      # cook | stranger | none


class OtpBody(BaseModel):
    code: str


def create_app(settings: Settings | None = None, db: DB | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or DB(settings.db_path)
    controls = MockControls()
    agent = build_agent(settings, db, controls)
    app = FastAPI(title="CookSmart")
    app.state.agent, app.state.db, app.state.controls = agent, db, controls

    def need(hid: str) -> dict:
        h = repo.get_household(db, hid)
        if not h:
            raise HTTPException(404, "unknown household")
        return h

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    # ---- households
    @app.post("/api/households")
    def create_household(body: HouseholdBody):
        if repo.get_household(db, body.id):
            return {"id": body.id, "created": False}
        today = dt.date.today().isoformat()
        repo.create_household(db, body.id, body.name, today, owner_phone=body.owner_phone,
                              cook_phone=body.cook_phone, cook_voice_enrolled=1,
                              preferences={"diet": "vegetarian", "dislikes": [], "likes": []})
        if body.seed:
            inv.seed_demo(db, body.id, today)
        return {"id": body.id, "created": True}

    @app.get("/api/{hid}/owner/state")
    def owner_state(hid: str):
        h = need(hid)
        plan = repo.latest_plan(db, hid)
        items = inv.list_items(db, hid)
        cook_day = plan["day"] if plan else h["sim_date"]
        for i in items:
            i["doubtful"] = inv.is_doubtful(i, h["sim_date"])
            i["spoiled"] = inv.is_spoiled(i, cook_day)
            i["days_left"] = inv.days_left(i, cook_day)
        return {"household": h, "inventory": items, "plan": plan, "orders": repo.list_orders(db, hid),
                "audit": repo.list_audit(db, hid), "memory": repo.list_memory(db, hid),
                "controls": controls.as_dict(), "nlu_source": agent.nlu.last_source,
                "planner": "claude" if agent.planner.claude else "heuristic"}

    @app.get("/api/{hid}/owner/messages")
    def owner_messages(hid: str, after: int = 0):
        need(hid)
        return repo.list_messages(db, hid, "owner", after)

    @app.get("/api/{hid}/cook/messages")
    def cook_messages(hid: str, after: int = 0):
        """Everything the cook's chat can ever show. Deliberately a separate, minimal endpoint."""
        need(hid)
        return repo.list_messages(db, hid, "cook", after)

    @app.post("/api/{hid}/owner/message")
    def owner_message(hid: str, body: TextBody):
        need(hid)
        agent.handle_owner(hid, body.text)
        return {"ok": True}

    @app.post("/api/{hid}/cook/message")
    def cook_message(hid: str, body: TextBody):
        need(hid)
        agent.handle_cook(hid, body.text, voice=body.voice)
        return {"ok": True}

    @app.post("/api/{hid}/settings")
    def settings_route(hid: str, body: SettingsBody):
        need(hid)
        agent.set_settings(hid, body.order_mode, body.auto_cap)
        return {"ok": True}

    # ---- triggers: what a scheduler (cron/Celery) calls in production
    @app.post("/api/{hid}/trigger/{name}")
    def trigger(hid: str, name: str):
        need(hid)
        actions = {
            "nightly_review": agent.nightly_review, "cutoff": agent.cutoff,
            "morning": agent.morning_handoff, "check_orders": agent.check_orders,
            "end_of_day": agent.end_of_day, "close_day": agent.close_day,
        }
        if name not in actions:
            raise HTTPException(404, "unknown trigger")
        actions[name](hid)
        return {"ok": True}

    # ---- door
    @app.post("/api/{hid}/door/arrive")
    def door_arrive(hid: str, body: DoorBody):
        need(hid)
        return agent.rider_arrives(hid, body.voice)

    @app.post("/api/{hid}/door/otp")
    def door_otp(hid: str, body: OtpBody):
        need(hid)
        return agent.door_otp(hid, body.code)

    # ---- mock rail switches
    @app.post("/api/mock/controls")
    def set_controls(data: dict):
        if data.get("reset"):
            controls.reset()
        controls.update(data)
        return controls.as_dict()

    # ---- WhatsApp Cloud API webhook (Meta format); the mock UI doesn't need it
    @app.get("/webhook/whatsapp")
    def verify(mode: str = Query(None, alias="hub.mode"), token: str = Query(None, alias="hub.verify_token"),
               challenge: str = Query(None, alias="hub.challenge")):
        if mode == "subscribe" and token == settings.whatsapp_verify_token:
            return PlainTextResponse(challenge or "")
        raise HTTPException(403, "bad verify token")

    @app.post("/webhook/whatsapp")
    async def whatsapp(request: Request):
        payload = await request.json()
        handled = 0
        for sender, text in parse_meta_payload(payload):
            found = repo.find_household_by_phone(db, sender)
            if not found:
                continue
            h, role = found
            if role == "owner":
                agent.handle_owner(h["id"], text)
            else:
                agent.handle_cook(h["id"], text, voice=False)
            handled += 1
        return {"handled": handled}

    return app


def parse_meta_payload(payload: dict):
    """Yield (sender_phone, text) from a WhatsApp Cloud API webhook body (text messages only for now;
    voice notes arrive as audio media ids that must be downloaded and sent to STT)."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                if msg.get("type") == "text":
                    yield msg["from"], msg["text"]["body"]


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
