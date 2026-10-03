import datetime as dt
import os

import pytest

os.environ.pop("ANTHROPIC_API_KEY", None)   # tests always run on the offline path

from cooksmart import inventory as inv, repo, scenarios                      # noqa: E402
from cooksmart.api import build_agent                               # noqa: E402
from cooksmart.config import Settings                               # noqa: E402
from cooksmart.db import DB                                         # noqa: E402
from cooksmart.providers.controls import MockControls               # noqa: E402

DAY = "2026-10-01"


@pytest.fixture
def env():
    db = DB(":memory:")
    controls = MockControls()
    settings = Settings(":memory:", "", "m", "", "t")
    agent = build_agent(settings, db, controls)
    repo.create_household(db, "demo", "Demo", DAY, cook_voice_enrolled=1,
                          preferences={"diet": "vegetarian", "dislikes": [], "likes": []})
    inv.seed_demo(db, "demo", DAY)

    class E:
        pass
    e = E()
    e.db, e.controls, e.agent, e.hid = db, controls, agent, "demo"
    raw = agent.handle_owner                    # tests use the scenario shorthand: a pick or a named dish settles the whole menu
    e.agent.handle_owner = lambda hid, text: scenarios.say_and_settle(type("A", (), {"handle_owner": staticmethod(raw)}), db, hid, text)
    e.raw_owner = raw
    e.owner = lambda: [m["text"] for m in repo.list_messages(db, "demo", "owner")]
    e.cook = lambda: [m["text"] for m in repo.list_messages(db, "demo", "cook")]
    e.plan = lambda: repo.latest_plan(db, "demo")
    e.orders = lambda: repo.list_orders(db, "demo")
    return e
