"""FastAPI app: mock WhatsApp UI endpoints, trigger endpoints (what the scheduler will call), and a
Meta-format WhatsApp webhook so the real channel can be swapped in later."""
from __future__ import annotations

import datetime as dt
import json
import hmac
from pathlib import Path

from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import callresult, daystory, gnani_kb, gnani_prompt, studio
from . import inventory as inv
from . import profile as prof
from . import repo, scenarios
from .agent import Agent
from .channels import MockChannel
from .config import Settings, get_settings
from .db import DB
from .nlu import NLU, ClaudeNLU
from .planner import ClaudePlanner, Planner, menu_name
from .recipes import ITEMS
from .providers.controls import MockControls
from .providers.dispatch import MockDispatchProvider
from .providers.grocery import MockGroceryProvider
from .providers.payment import MockPaymentProvider
from .providers.calls import GnaniCallProvider, MockCallProvider
from .providers.gnani import GnaniSpeechProvider
from .providers.gnani_platform import GnaniPlatform, PlatformError
from .providers.speech import MockSpeechProvider, ResilientSpeech
from .providers.voice import MockVoiceVerifier

STATIC = Path(__file__).parent / "static"


def build_speech(settings: Settings, controls: MockControls):
    """Gnani for the cook's voice when a key is configured (COOKSMART_SPEECH=auto|gnani|mock)."""
    mock = MockSpeechProvider(controls)
    if settings.speech == "mock" or (settings.speech == "auto" and not settings.gnani_api_key):
        return mock
    if not settings.gnani_api_key:
        raise RuntimeError("COOKSMART_SPEECH=gnani needs GNANI_API_KEY")
    gnani = GnaniSpeechProvider(settings.gnani_api_key, stt_url=settings.gnani_stt_url, tts_url=settings.gnani_tts_url,
                                voice=settings.gnani_voice, model=settings.gnani_model)
    return ResilientSpeech(gnani, mock, controls)


def build_platform(settings: Settings) -> GnaniPlatform | None:
    return GnaniPlatform(settings.inya_platform_key) if settings.inya_platform_key else None


def build_caller(settings: Settings, platform: GnaniPlatform | None = None):
    """The Gnani voice agent that phones the cook, or a mock that records the call."""
    if platform and settings.inya_bot_id:
        return GnaniCallProvider(platform, settings.inya_bot_id, settings.inya_environment)
    return MockCallProvider()


def build_agent(settings: Settings, db: DB, controls: MockControls, platform: GnaniPlatform | None = None) -> Agent:
    claude_planner = claude_nlu = None
    if settings.anthropic_api_key:
        claude_planner = ClaudePlanner(settings.anthropic_api_key, settings.model)
        claude_nlu = ClaudeNLU(settings.anthropic_api_key, settings.model)
    speech = build_speech(settings, controls)
    return Agent(db, MockChannel(db, speech), Planner(claude_planner), NLU(claude_nlu), speech,
                 MockGroceryProvider(controls), MockDispatchProvider(), MockPaymentProvider(controls),
                 MockVoiceVerifier(), build_caller(settings, platform))


class TextBody(BaseModel):
    text: str
    voice: bool = True


class SettingsBody(BaseModel):
    order_mode: str | None = None
    auto_cap: int | None = None
    cook_channel: str | None = None       # "chat" | "call"
    cook_phone: str | None = None


class SimulateBody(BaseModel):
    kind: str = "brief_ok"
    item: str | None = None


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
    if st == "ordered" and open_order:
        return dict(step=6, label="🛵 Groceries arrive (15 min)", action={"kind": "door", "voice": "cook"},
                    hint="Rider at the door. Try a stranger's voice from Stock & logs to see the OTP check.")
    if st in ("ready", "ordered"):
        label = "☀️ Morning: cook arrives"
        hint = "The agent re-checks the order, then briefs the cook. The cook can also just message *aa gayi*."
        return dict(step=6 if st == "ordered" else 4, label=label, action=trig("morning"), hint=hint)
    if st == "briefed":
        todo = [m for m in daystory.MEALS if m not in plan.get("served", [])]
        if todo and not open_order:
            m = todo[0]
            return dict(step=7, label=f"🍽️ {m.title()} is served", action=trig("serve_" + m),
                        hint="The cook makes it, the family eats, and the fridge shelves go down.")
        if open_order:
            return dict(step=7, label="🛵 Rider arrives (cook's voice)", action={"kind": "door", "voice": "cook"},
                        hint="Try the stranger's voice from the Door panel to see the OTP fallback.")
        return dict(step=8, label="🌙 Wrap up: ask the cook what was used", action=trig("end_of_day"),
                    hint="Or the cook can message *khana ban gaya*.")
    return dict(step=8, label="✅ Close the day", action=trig("close_day"),
                hint="Answer the agent in the cook chat first (e.g. *paneer khatam*, then *haan*).")


class PromptBody(BaseModel):
    content: str
    force: bool = False


class PreviewBody(BaseModel):
    content: str | None = None
    call_type: str = "brief"


class DocBody(BaseModel):
    content: str
    name: str | None = None


class FaqBody(BaseModel):
    faqs: list[dict]


class RestoreBody(BaseModel):
    version_id: int


def create_app(settings: Settings | None = None, db: DB | None = None, platform: GnaniPlatform | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = db or DB(settings.db_path)
    controls = MockControls()
    platform = platform or build_platform(settings)
    agent = build_agent(settings, db, controls, platform)
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
            if i["days_left"] is not None:
                by = dt.date.fromisoformat(cook_day) + dt.timedelta(days=i["days_left"])
                i["use_by"] = by.strftime("%a")
                i["within"] = max(0, (by - dt.date.fromisoformat(h["sim_date"])).days)
        orders = repo.list_orders(db, hid)
        used = daystory.consumed_so_far(plan, float(plan["flags"].get("scale", 1.0))) if plan else {}
        incoming = {}
        for o in orders:
            if o["status"] == "accepted":
                for l in o["items"]:
                    incoming[l["name"]] = incoming.get(l["name"], 0) + l["qty"]
        for i in items:
            i.update(daystory.view(i["name"]))
            i["shown"] = round(max(0.0, i["qty"] - used.get(i["name"], 0.0)), 1)
            i["incoming"] = incoming.pop(i["name"], 0)
        extra = [{"name": n, "qty": 0, "shown": 0, "unit": ITEMS[n]["unit"], "incoming": q, "days_left": None,
                  "doubtful": False, "spoiled": False, **daystory.view(n)} for n, q in incoming.items() if n in ITEMS]
        story = repo.list_story(db, hid, plan["id"]) if plan else []
        return {"fridge": items + extra, "story": story, "meals": daystory.meals_of(plan) if plan else {},
                "served": plan["served"] if plan else [],
                "meal_names": {m: menu_name(v) for m, v in daystory.meals_of(plan).items() if v} if plan else {}, "household": h, "inventory": items, "plan": plan, "orders": repo.list_orders(db, hid),
                "audit": repo.list_audit(db, hid), "memory": repo.list_memory(db, hid),
                "controls": controls.as_dict(), "nlu_source": agent.nlu.last_source,
                "planner": agent.planner.last_source if agent.planner.claude else "heuristic",
                "speech": agent.speech.describe(),
                "calls": repo.list_calls(db, hid), "call_provider": agent.caller.describe() if agent.caller else None,
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

    MAX_VOICE_BYTES = 2_500_000

    @app.post("/api/{hid}/cook/voice")
    async def cook_voice(hid: str, request: Request):
        """A recorded voice note from the cook (16 kHz mono WAV). The optional X-Transcript-Hint header carries
        the browser's own transcript, used only when no speech service is configured."""
        need(hid)
        audio = await request.body()
        if not audio:
            raise HTTPException(400, "empty audio")
        if len(audio) > MAX_VOICE_BYTES:
            raise HTTPException(413, "voice note too long")
        hint = unquote(request.headers.get("x-transcript-hint", "")) or None
        agent.handle_cook_audio(hid, audio, request.headers.get("content-type", "audio/wav"), hint)
        return {"ok": True}

    @app.get("/api/{hid}/media/{media_id}")
    def media(hid: str, media_id: int):
        need(hid)
        m = repo.get_media(db, hid, media_id)
        if not m:
            raise HTTPException(404, "no such media")
        return Response(m["data"], media_type=m["mime"])

    @app.post("/api/{hid}/settings")
    def settings_route(hid: str, body: SettingsBody):
        h = need(hid)
        agent.set_settings(hid, body.order_mode, body.auto_cap)
        if body.cook_channel in ("chat", "call"):
            repo.update_household(db, hid, preferences={**h["preferences"], "cook_channel": body.cook_channel})
            repo.audit(db, hid, "cook_channel", channel=body.cook_channel)
        if body.cook_phone is not None:
            repo.update_household(db, hid, cook_phone=body.cook_phone.strip() or None)
        return {"ok": True}

    # ---- Gnani cook-call agent: webhook, live action, dynamic message. Off unless GNANI_WEBHOOK_TOKEN is set.
    def check_token(token: str) -> None:
        if not settings.gnani_webhook_token:
            raise HTTPException(503, "Gnani endpoints are disabled: set GNANI_WEBHOOK_TOKEN")
        if not hmac.compare_digest(token or "", settings.gnani_webhook_token):
            raise HTTPException(401, "bad token")

    @app.post("/gnani/webhook/call-ended")
    async def gnani_webhook(request: Request, token: str = ""):
        check_token(token)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(400, "body must be JSON")
        return agent.handle_call_result(payload)       # always 2xx for a known call; Gnani retries on errors

    @app.post("/gnani/action/{hid}/cook-problem")
    async def gnani_cook_problem(hid: str, request: Request, token: str = ""):
        check_token(token)
        need(hid)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        args = body.get("arguments", body) if isinstance(body, dict) else {}
        reason = str(args.get("problem") or args.get("reason") or args.get("type") or "").lower()
        text = agent.live_cook_problem(hid, reason, args.get("item"))
        return {"text": text, "additional_info": {"inya_data": {"text": text, "user_context": {}}}}

    @app.api_route("/gnani/dynamic/{hid}/brief", methods=["GET", "POST"])
    def gnani_dynamic(hid: str, token: str = ""):
        check_token(token)
        need(hid)
        d = agent.dynamic_brief(hid)
        return {"additional_info": {"inya_data": {"text": d["text"], "user_context": d["user_context"]}}}

    @app.get("/api/{hid}/gnani/kb")
    def gnani_kb_view(hid: str):
        """The knowledge base this household's Gnani agent would be given (also written by `gnani_cli kb`)."""
        h = need(hid)
        return {"files": {d["name"]: d["content"] for d in studio.current_docs(db, hid, h["preferences"], h["family_size"])},
                "faqs": studio.current_faqs(db, hid, h["preferences"])[0]}

    @app.post("/api/{hid}/profile/demo")
    def load_demo_family(hid: str):
        h = need(hid)
        demo = {k: v for k, v in gnani_kb.DEMO_PROFILE.items() if k != "diet"}
        repo.update_household(db, hid, preferences={**h["preferences"], **demo})
        repo.audit(db, hid, "demo_family_loaded")
        return {"ok": True}

    # ---- Agent Studio: edit the cook-call agent's prompt, knowledge base, FAQs and the household profile
    def studio_state(hid: str) -> dict:
        h = need(hid)
        prompt, p_over = studio.current_prompt(db, hid)
        faqs, faq_default, f_over = studio.current_faqs(db, hid, h["preferences"])
        prefs = h["preferences"]
        can_push = platform is not None and bool(settings.inya_bot_id)
        return {
            "prompt": {"current": prompt, "default": gnani_prompt.load_prompt(), "overridden": p_over,
                       "history": studio.history(db, hid, "prompt", studio.PROMPT),
                       "checks": studio.check_prompt(prompt), "variables": [{"name": n, "about": a} for n, a in studio.VARIABLES]},
            "docs": [{**d, "history": studio.history(db, hid, "doc", d["name"])}
                     for d in studio.current_docs(db, hid, prefs, h["family_size"])],
            "faqs": {"items": faqs, "default": faq_default, "overridden": f_over, "history": studio.history(db, hid, "faqs", "faqs")},
            "profile": {"family_size": h["family_size"], "diet": prefs.get("diet", "vegetarian"),
                        "lactose_free": bool(prefs.get("lactose_free")), "cook_name": prefs.get("cook_name", ""),
                        "cook_phone": h["cook_phone"] or "", "members": prefs.get("members", []), "style": prefs.get("style", {}),
                        "customs": prefs.get("customs", []), "kitchen": prefs.get("kitchen", {}),
                        "units": prefs.get("units", {"katori_ml": 150})},
            "options": {"allergens": {g: m["hi"] for g, m in prof.ALLERGENS.items()},
                        "health": {k: v for k, v in prof.HEALTH_TO_INSTRUCTION.items()},
                        "age_groups": prof.AGE_GROUPS, "spice": list(prof.SPICE_HI), "diets": list(prof.DIETS),
                        "weekdays": list(prof.WEEKDAYS)},
            "push": {"available": can_push, "reason": "" if can_push else
                     "Set INYA_PLATFORM_KEY and INYA_BOT_ID in .env to push the prompt to your Gnani agent."},
        }

    @app.get("/api/{hid}/studio")
    def studio_get(hid: str):
        return studio_state(hid)

    @app.put("/api/{hid}/studio/prompt")
    def studio_prompt_save(hid: str, body: PromptBody):
        need(hid)
        checks = studio.check_prompt(body.content)
        if checks["errors"]:
            raise HTTPException(422, {"errors": checks["errors"], "warnings": checks["warnings"]})
        if checks["blocking_safety"] and not body.force:
            raise HTTPException(409, {"needs_force": True, "warnings": checks["warnings"]})
        studio.save(db, hid, "prompt", studio.PROMPT, body.content)
        repo.audit(db, hid, "studio_prompt_saved", chars=len(body.content), forced=body.force)
        return {"saved": True, "warnings": checks["warnings"]}

    @app.delete("/api/{hid}/studio/prompt")
    def studio_prompt_reset(hid: str):
        need(hid)
        studio.reset(db, hid, "prompt", studio.PROMPT)
        return {"reset": True}

    @app.post("/api/{hid}/studio/prompt/preview")
    def studio_prompt_preview(hid: str, body: PreviewBody):
        """Render the prompt exactly as the agent will receive it, with today's real variables if there is a menu."""
        need(hid)
        content = body.content if body.content is not None else studio.current_prompt(db, hid)[0]
        if body.call_type not in ("brief", "reconcile"):
            raise HTTPException(400, "call_type must be brief or reconcile")
        try:
            return studio.preview(db, hid, content, body.call_type, studio.live_variables(db, hid, body.call_type))
        except Exception as e:
            raise HTTPException(422, {"errors": [str(e)]})

    @app.post("/api/{hid}/studio/prompt/push")
    def studio_prompt_push(hid: str):
        need(hid)
        if platform is None or not settings.inya_bot_id:
            raise HTTPException(409, "Set INYA_PLATFORM_KEY and INYA_BOT_ID first.")
        content = studio.current_prompt(db, hid)[0]
        try:
            platform.validate_prompt(content)
            platform.update_agent(settings.inya_bot_id, {"systemPrompt": content})
        except PlatformError as e:
            raise HTTPException(502, str(e))
        repo.audit(db, hid, "studio_prompt_pushed", bot=settings.inya_bot_id)
        return {"pushed": True}

    @app.put("/api/{hid}/studio/docs/{name}")
    def studio_doc_save(hid: str, name: str, body: DocBody):
        h = need(hid)
        defaults = gnani_kb.build_docs(h["preferences"], h["family_size"])
        if name not in defaults and not studio.CUSTOM_RE.match(name):
            raise HTTPException(404, "unknown document")
        checks = studio.check_doc(name, body.content)
        if checks["errors"]:
            raise HTTPException(422, {"errors": checks["errors"], "warnings": []})
        studio.save(db, hid, "doc", name, body.content)
        repo.audit(db, hid, "studio_doc_saved", doc=name, chars=len(body.content))
        return {"saved": True, "warnings": checks["warnings"]}

    @app.post("/api/{hid}/studio/docs")
    def studio_doc_create(hid: str, body: DocBody):
        need(hid)
        name = (body.name or "").strip().lower()
        if not studio.CUSTOM_RE.match(name):
            raise HTTPException(422, {"errors": ["Name it like custom_festivals.md (letters, digits, - and _)."]})
        if sum(d["custom"] for d in studio.current_docs(db, hid, {}, 4)) >= 20:
            raise HTTPException(422, {"errors": ["At most 20 custom documents."]})
        checks = studio.check_doc(name, body.content)
        if checks["errors"]:
            raise HTTPException(422, {"errors": checks["errors"], "warnings": []})
        studio.save(db, hid, "doc", name, body.content)
        return {"saved": True, "warnings": checks["warnings"]}

    @app.delete("/api/{hid}/studio/docs/{name}")
    def studio_doc_reset(hid: str, name: str):
        need(hid)
        studio.reset(db, hid, "doc", name)
        return {"reset": True}

    @app.put("/api/{hid}/studio/faqs")
    def studio_faqs_save(hid: str, body: FaqBody):
        need(hid)
        checks = studio.check_faqs(body.faqs)
        if checks["errors"]:
            raise HTTPException(422, {"errors": checks["errors"], "warnings": []})
        studio.save(db, hid, "faqs", "faqs", json.dumps(body.faqs, ensure_ascii=False))
        return {"saved": True, "warnings": checks["warnings"]}

    @app.delete("/api/{hid}/studio/faqs")
    def studio_faqs_reset(hid: str):
        need(hid)
        studio.reset(db, hid, "faqs", "faqs")
        return {"reset": True}

    @app.post("/api/{hid}/studio/restore")
    def studio_restore(hid: str, body: RestoreBody):
        need(hid)
        if not studio.restore(db, hid, body.version_id):
            raise HTTPException(404, "no such version")
        return {"restored": True}

    @app.put("/api/{hid}/studio/profile")
    def studio_profile_save(hid: str, data: dict):
        h = need(hid)
        clean, errors = prof.sanitize_profile(data)
        if errors:
            raise HTTPException(422, {"errors": errors})
        columns = {k: clean.pop(k) for k in ("family_size", "cook_phone") if k in clean}
        repo.update_household(db, hid, preferences={**h["preferences"], **clean}, **columns)
        repo.audit(db, hid, "profile_edited", fields=sorted([*clean, *columns]))
        return {"saved": True}

    @app.get("/api/{hid}/studio/export.zip")
    def studio_export(hid: str):
        h = need(hid)
        return Response(studio.export_zip(db, hid, h["preferences"], h["family_size"]), media_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="cooksmart-gnani-agent.zip"'})

    @app.post("/api/{hid}/calls/{ref:path}/simulate")
    def simulate_call(hid: str, ref: str, body: SimulateBody):
        """Feed a Gnani-shaped webhook through the real handler, so the whole loop can be tried without telephony."""
        need(hid)
        call = repo.get_call(db, ref)
        if not call or call["household_id"] != hid:
            raise HTTPException(404, "unknown call")
        plan = repo.latest_plan(db, hid)
        menu = list(inv.needs_for(plan["chosen"])) if plan and plan["chosen"] else []
        stocked = [i["name"] for i in inv.list_items(db, hid) if i["qty"] > 0]
        items = [body.item] if body.item else callresult.pick_items(body.kind, menu, stocked)
        return agent.handle_call_result(callresult.simulated_payload(body.kind, call, items))

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
            **{f"serve_{m}": (lambda h, m=m: agent.serve_meal(h, m)) for m in daystory.MEALS},
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
