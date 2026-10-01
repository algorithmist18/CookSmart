"""The Claude integration, exercised with a stand-in client (no network, no key)."""
from types import SimpleNamespace as NS

import pytest

from cooksmart import inventory as inv
from cooksmart.nlu import NLU, ClaudeNLU
from cooksmart.planner import ClaudePlanner, PlanContext, Planner, heuristic_propose
from cooksmart.recipes import RECIPES


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.calls = payload, error, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return NS(content=[NS(type="tool_use", input=self.payload)])


def ctx():
    stock = {"spinach": {"qty": 300, "unit": "g", "days_left": 1}, "paneer": {"qty": 200, "unit": "g", "days_left": 3},
             "onion": {"qty": 6, "unit": "pcs", "days_left": 15}, "tomato": {"qty": 4, "unit": "pcs", "days_left": 2},
             "atta": {"qty": 800, "unit": "g", "days_left": None}, "dal": {"qty": 500, "unit": "g", "days_left": None},
             "cream": {"qty": 100, "unit": "ml", "days_left": 5}, "chicken": {"qty": 500, "unit": "g", "days_left": 1}}
    return PlanContext(cook_day="2026-10-02", stock=stock, preferences={"diet": "vegetarian"})


def claude_planner(client):
    p = object.__new__(ClaudePlanner)
    p.client, p.model = client, "test-model"
    return p


def test_claude_menus_are_validated_and_gaps_computed_by_code():
    client = FakeClient({"menus": [
        {"dish_ids": ["palak_paneer", "roti"], "reason": "Uses the spinach that expires tomorrow."},
        {"dish_ids": ["chicken_curry"], "reason": "Chicken is expiring."},          # not allowed: vegetarian
        {"dish_ids": ["not_a_recipe", "dal_tadka"], "reason": "Hallucinated id is dropped."},
        {"dish_ids": ["palak_paneer"], "reason": "Duplicate main is dropped."},
    ]})
    out = claude_planner(client).propose(ctx())
    assert [p.recipe_ids for p in out.items] == [["palak_paneer", "roti"], ["dal_tadka"]]
    assert out.items[0].reason == "Uses the spinach that expires tomorrow."
    assert out.items[0].feasible and out.source == "claude"
    # the prompt only offers recipes the household may eat
    sent = client.calls[0]["messages"][0]["content"]
    assert "chicken_curry" not in sent and "palak_paneer" in sent
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": "propose_menu"}


def test_claude_rejected_mains_are_not_resurrected():
    c = ctx(); c.exclude_ids = {"palak_paneer"}
    out = claude_planner(FakeClient({"menus": [{"dish_ids": ["palak_paneer"], "reason": "x"},
                                               {"dish_ids": ["dal_tadka"], "reason": "y"}]})).propose(c)
    assert [p.recipe_ids[0] for p in out.items] == ["dal_tadka"]


@pytest.mark.parametrize("client", [FakeClient(error=RuntimeError("api down")), FakeClient({"menus": []}),
                                    FakeClient({"menus": [{"dish_ids": ["nope"], "reason": "x"}]})])
def test_planner_falls_back_to_heuristics_on_any_claude_problem(client):
    planner = Planner(claude_planner(client))
    out = planner.propose(ctx())
    assert out.source == "heuristic" and out.items
    assert planner.last_source == "heuristic"


def test_claude_nlu_output_is_sanitised_and_falls_back():
    good = ClaudeNLU.__new__(ClaudeNLU)
    good.client, good.model = FakeClient({"intents": [
        {"type": "used_up", "item": "paneer"}, {"type": "used_up", "item": "unobtainium"},
        {"type": "teleport"}]}), "m"
    nlu = NLU(good)
    assert nlu.cook("paneer khatam") == [{"type": "used_up", "item": "paneer"}]
    assert nlu.last_source == "claude"

    broken = ClaudeNLU.__new__(ClaudeNLU)
    broken.client, broken.model = FakeClient(error=TimeoutError()), "m"
    nlu = NLU(broken)
    assert nlu.cook("paneer khatam")[0] == {"type": "used_up", "item": "paneer"}
    assert nlu.last_source == "rules"


def test_heuristic_alone_is_deterministic():
    a, b = heuristic_propose(ctx()), heuristic_propose(ctx())
    assert [p.recipe_ids for p in a.items] == [p.recipe_ids for p in b.items]
