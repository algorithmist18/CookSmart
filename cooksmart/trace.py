"""A running log of what comes in, what goes to Gnani (and what comes back), and what is sent to people.

It exists so the owner (or a developer) can see exactly what happened, in a side panel. Nothing here changes behaviour:
without a sink (tests that build the agent directly) every call is a no-op. Secrets never reach the log.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

_hid: ContextVar[str | None] = ContextVar("trace_household", default=None)
_sink = None                     # callable(**row) set by the app
SECRET = ("key", "token", "authorization", "password", "secret")


def set_sink(fn) -> None:
    global _sink
    _sink = fn


def bind(hid: str | None) -> None:
    """Which household the calls made from here on belong to (per request / thread)."""
    _hid.set(hid)


def redact(obj, depth: int = 0):
    if isinstance(obj, (bytes, bytearray)):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, dict):
        return {k: ("***" if any(s in str(k).lower() for s in SECRET) else redact(v, depth + 1)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        items = [redact(v, depth + 1) for v in obj[:40]]
        return items + [f"... {len(obj) - 40} more"] if len(obj) > 40 else items
    if isinstance(obj, str) and len(obj) > 1800:
        return obj[:1800] + f"... [{len(obj)} chars]"
    return obj


def record(kind: str, label: str, request=None, response=None, status: str = "ok", ms: int | None = None,
           hid: str | None = None) -> None:
    hid = hid or _hid.get()
    if _sink is None or not hid:
        return
    try:
        _sink(household_id=hid, kind=kind, label=label, request=redact(request), response=redact(response),
              status=status, ms=ms)
    except Exception:            # logging must never break the kitchen
        pass


@contextmanager
def timed():
    """with trace.timed() as t: ...; t.ms"""
    class T:
        ms = 0
    t, t0 = T(), time.perf_counter()
    try:
        yield t
    finally:
        t.ms = int((time.perf_counter() - t0) * 1000)
