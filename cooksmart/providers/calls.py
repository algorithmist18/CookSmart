"""Phone calls to the cook. Gnani's hosted agent does the talking; CookSmart decides what it knows and applies
what it reports. The mock records the call so the whole loop works offline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .. import trace
from .gnani_platform import GnaniPlatform


@dataclass
class CallRequest:
    household_id: str
    reference_id: str
    call_type: str
    phone: str
    variables: dict


@dataclass
class CallStarted:
    reference_id: str
    provider: str
    conversation_id: str | None = None


class CallProvider(Protocol):
    def start_call(self, req: CallRequest) -> CallStarted: ...
    def describe(self) -> dict: ...


@dataclass
class MockCallProvider:
    placed: list[CallRequest] = field(default_factory=list)
    fail_next: bool = False

    def start_call(self, req):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("the call could not be placed")
        self.placed.append(req)
        trace.record("gnani", "Gnani call (mock): trigger_call", {"note": "no Gnani key: nothing was sent", "phoneNumber": req.phone,
                     "clientReferenceId": req.reference_id, "variables": req.variables}, {"status": "mock", "conversationId": None},
                     hid=req.household_id)
        return CallStarted(req.reference_id, "mock")

    def describe(self):
        return {"calls": "mock (simulate outcomes in the panel)", "live": False}


class GnaniCallProvider:
    def __init__(self, platform: GnaniPlatform, bot_id: str, environment: str = "development"):
        self.platform, self.bot_id, self.environment = platform, bot_id, environment

    def start_call(self, req):
        body = self.platform.trigger_call(self.bot_id, req.phone, req.variables, req.reference_id, self.environment)
        resp = body.get("response") or {}
        conv = resp.get("conversationId") or resp.get("conversation_id") if isinstance(resp, dict) else None
        return CallStarted(req.reference_id, "gnani", conv)

    def describe(self):
        return {"calls": f"Gnani agent ({self.environment})", "live": True}
