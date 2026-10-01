"""FastAPI app: mock WhatsApp UI endpoints, trigger endpoints (what the scheduler will call), and a
Meta-format WhatsApp webhook so the real channel can be swapped in later."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import inventory as inv
from . import repo, scenarios
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


def next_step(plan: dict | None, orders: list[dict]) -> dict:
    """The guided 'what happens next' card plus the S1-S8 stepper position."""
    open_order = any(o["status"] == "accepted" for o in orders)
    trig = lambda name: {"kind": "trigger", "name": name}
    if not plan or plan["state"] == "closed":
        return dict(step=0, label="🌙 Run the nightly review", action=trig("nightly_review"),
                    hint="After dinner the agent checks the kitchen and proposes tomorrow's meal.")
    st = plan["state"]
    if st == "review":
        return dict(step=3, label="⏰ Owner stays silent (cutoff)", action=trig("cutoff"),
                    hint="Reply in the owner chat to choose a menu, or press this to see what happens when you don't.")
    if st == "approval":
        return dict(step=5, label="⏰ No approval in time (cutoff)", action=trig("cutoff"),
                    hint="Reply *approve* in the owner chat, or press this to see the agent hold the order.")
    if st == "held":
        return dict(step=5, label="☀️ Morning: cook arrives", action=trig("morning"),
                    hint="The order is on hold. Approve it in the chat, or let the morning come and see the fallback.")
    if st in ("ready", "ordered"):
        label = "☀️ Morning: cook arrives"
        hint = "The agent re-checks the order, then briefs the cook. The cook can also just message *aa gayi*."
        return dict(step=6 if st == "ordered" else 4, label=label, action=trig("morning"), hint=hint)
    if st == "briefed":
        if open_order:
            return dict(step=7, label="🛵 Rider arrives (cook's voice)", action={"kind": "door", "voice": "cook"},
                        hint="Try the stranger's voice from the Door panel to see the OTP fallback.")
        return dict(step=7, label="🌙 Evening: ask the cook what was used", action=trig("end_of_day"),
                    hint="Or the cook can message *khana ban gaya*.")
    return dict(step=8, label="✅ Close the day", action=trig("close_day"),
                hint="Answer the agent in the cook chat first (e.g. *paneer khatam*, then *haan*).")


def create_app(settings: Settings | None = None, db: DB | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or DB(settings.db_path)
    controls = MockControls()
    agent = build_agent(settings, db, controls)
    app = FastAPI(title="CookSmart")
    app.state.agent, app.state.db, app.state.controls = agent, db, controls
    current: dict[str, str] = {}

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
                "planner": agent.planner.last_source if agent.planner.claude else "heuristic",
                "next": next_step(plan, repo.list_orders(db, hid)),
                "scenario": ({k: v for k, v in scenarios.BY_ID[current[hid]].__dict__.items() if k in ("id", "title", "emoji", "blurb", "hint")} if hid in current else None)}

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

    # ---- scenarios
    @app.get("/api/scenarios")
    def scenario_list():
        return scenarios.catalog()

    @app.post("/api/{hid}/scenario/{sid}")
    def load_scenario(hid: str, sid: str, play: bool = False):
        need(hid)
        if sid not in scenarios.BY_ID:
            raise HTTPException(404, "unknown scenario")
        sc = scenarios.load(db, controls, hid, sid)
        current[hid] = sid
        if play:
            scenarios.play(agent, db, controls, hid, sc.script)
        return {"ok": True, "reset": True, "played": play}

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
