"""Gnani Agent Builder Platform API (base https://api.inya.ai/platform, header x-api-key).

Paths and the response envelope {status, requestId, message, response} are from Gnani's documentation as
summarised in the project's knowledge file. Request-body field names are marked "indicative" there: if Gnani
answers 400, its message names the field, and PlatformError surfaces it verbatim.
"""
from __future__ import annotations

import httpx

BASE = "https://api.inya.ai/platform"


class PlatformError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Gnani Platform HTTP {status}: {message}")
        self.status, self.message = status, message


class GnaniPlatform:
    def __init__(self, api_key: str, *, base: str = BASE, client: httpx.Client | None = None, timeout: float = 30.0):
        if not api_key:
            raise ValueError("INYA_PLATFORM_KEY is empty")
        self.api_key, self.base = api_key, base.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.client.request(method, self.base + path, headers={"x-api-key": self.api_key,
                                                                       "Content-Type": "application/json"}, **kw)
        except httpx.HTTPError as e:
            raise PlatformError(0, f"could not reach Gnani: {e}") from e
        try:
            body = r.json()
        except ValueError:
            body = {"message": r.text[:300]}
        if r.status_code >= 400:
            hint = {401: " (bad or missing key)", 403: " (key lacks permission)", 429: " (rate limited: back off)"}.get(r.status_code, "")
            raise PlatformError(r.status_code, f"{body.get('message') or body}{hint}")
        return body

    def validate_prompt(self, system_prompt: str) -> dict:
        return self._call("POST", "/v1/agents/prompt/validate", json={"systemPrompt": system_prompt})

    def create_agent(self, config: dict) -> str:
        body = self._call("POST", "/v1/agents", json=config)
        return (body.get("response") or {}).get("botId", "")

    def update_agent(self, bot_id: str, partial: dict) -> dict:
        return self._call("PUT", f"/v1/agents/{bot_id}", json=partial)

    def get_agent(self, bot_id: str) -> dict:
        return self._call("GET", f"/v1/agents/{bot_id}")

    def trigger_call(self, bot_id: str, phone: str, variables: dict, reference_id: str,
                     environment: str = "development") -> dict:
        """Outbound call. In development only whitelisted numbers can be called."""
        return self._call("POST", f"/v1/agents/{bot_id}/trigger_call", params={"environment": environment},
                          json={"phoneNumber": phone, "clientReferenceId": reference_id, "variables": variables})
