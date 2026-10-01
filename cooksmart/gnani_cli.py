"""Command line for the Gnani cook-call agent.

    python -m cooksmart.gnani_cli kb [--out gnani/kb] [--household demo]   write the knowledge base + FAQs
    python -m cooksmart.gnani_cli check                                    render the prompt locally (+ Gnani validate if a key is set)
    python -m cooksmart.gnani_cli deploy                                   create (or update, if INYA_BOT_ID is set) the agent
    python -m cooksmart.gnani_cli call --phone +91...                      trigger a test call (development: whitelisted numbers only)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import gnani_kb, gnani_prompt, repo
from .config import get_settings
from .db import DB
from .providers.gnani_platform import GnaniPlatform, PlatformError


def _prefs(household: str, db_path: str) -> tuple[dict, int]:
    try:
        h = repo.get_household(DB(db_path), household)
    except Exception:
        h = None
    if h and (h["preferences"].get("members") or h["preferences"].get("allergies")):
        return h["preferences"], h["family_size"]
    print(f"(no saved profile for '{household}': using the demo family)", file=sys.stderr)
    return gnani_kb.DEMO_PROFILE, 4


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cooksmart.gnani_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kb"); k.add_argument("--out", default="gnani/kb"); k.add_argument("--household", default="demo")
    sub.add_parser("check"); sub.add_parser("deploy")
    c = sub.add_parser("call"); c.add_argument("--phone", required=True); c.add_argument("--type", default="brief")
    a = ap.parse_args(argv)
    s = get_settings()

    if a.cmd == "kb":
        prefs, family = _prefs(a.household, s.db_path)
        for name in gnani_kb.write(a.out, prefs, family):
            print("wrote", f"{a.out}/{name}")
        print("\nUpload the .md files in the Gnani console (Agent > Knowledge base); faqs.json holds the exact-answer Q&A.")
        return 0

    if a.cmd == "check":
        prompt = gnani_prompt.load_prompt()
        for t in ("brief", "reconcile"):
            out = gnani_prompt.render(gnani_prompt.sample_variables(t), prompt)
            print(f"[local] {t} prompt renders OK ({len(out)} chars)")
        if s.inya_platform_key:
            try:
                print("[gnani] validate:", GnaniPlatform(s.inya_platform_key).validate_prompt(prompt))
            except PlatformError as e:
                print("[gnani] validate FAILED:", e)
                return 1
        else:
            print("[gnani] INYA_PLATFORM_KEY not set: skipped remote validation")
        return 0

    plat = GnaniPlatform(s.inya_platform_key) if s.inya_platform_key else None
    if plat is None:
        print("Set INYA_PLATFORM_KEY (Agent Builder Platform key) first.", file=sys.stderr)
        return 2
    try:
        if a.cmd == "deploy":
            cfg = {k: v for k, v in json.loads(gnani_prompt.CONFIG_PATH.read_text()).items() if not k.startswith("_")}
            cfg["systemPrompt"] = gnani_prompt.load_prompt()
            todo = [k for k, v in cfg.items() if isinstance(v, str) and v.startswith("TODO")]
            if todo:
                print("Fill these from the Gnani config endpoints in gnani/agent_config.json first:", ", ".join(todo))
                return 2
            if s.inya_bot_id:
                plat.update_agent(s.inya_bot_id, cfg)
                print("updated agent", s.inya_bot_id)
            else:
                print("created agent, botId =", plat.create_agent(cfg), "(put it in INYA_BOT_ID)")
        elif a.cmd == "call":
            from .cookbrief import CookBriefData, to_variables
            v = to_variables(CookBriefData(call_type=a.type, cook_name="दीदी", people=4, dishes=["दाल तड़का और रोटी"]))
            print(plat.trigger_call(s.inya_bot_id, a.phone, v, "cli-test", s.inya_environment))
    except PlatformError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
