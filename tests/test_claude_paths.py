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
    assert [p.meals["lunch"] for p in out.items] == [["palak_paneer", "roti"], ["dal_tadka"]]      # lunch is what Claude chose
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


# ------------------------------------------------------------------ understanding the owner better
def owner_nlu(client):
    c = object.__new__(ClaudeNLU)
    c.client, c.model = client, "test-model"
    return NLU(c)


CTX = {"state": "review", "stage": "lunch", "meals": {"breakfast": ["Poha"]},
       "options": [{"n": 1, "label": "Saves the most food", "dishes": ["Palak Paneer", "Roti"], "buy": []},
                   {"n": 2, "label": "Lightest", "dishes": ["Moong Khichdi"], "buy": ["moong"]}]}


def test_rules_understand_ordinals_typos_questions_and_restock():
    from cooksmart.nlu import parse_owner
    assert parse_owner("the second one please") == {"action": "choose", "choices": [2]}
    assert parse_owner("doosra wala")["action"] == "choose"
    assert parse_owner("pallak panner and roti") == {"action": "dish_request", "dishes": ["palak_paneer", "roti"]}
    assert parse_owner("what is expiring soon?")["action"] == "ask"
    assert parse_owner("why did you pick that?")["action"] == "ask"
    assert parse_owner("fill the fridge")["action"] == "restock" and parse_owner("please restock the kitchen")["action"] == "restock"
    assert parse_owner("can I have palak paneer?")["action"] == "dish_request"          # a dish named in a question is still a request
    assert parse_owner("I have 2 tomatoes left")["action"] == "stock"                    # 'two' is a quantity here, not option two


def test_claude_reads_the_owner_in_context_and_is_validated():
    client = FakeClient({"action": "choose", "choices": [2]})
    out = owner_nlu(client).owner("go with the lighter one", CTX)
    assert out == {"action": "choose", "choices": [2]}
    sent = client.calls[0]["messages"][0]["content"]
    assert "option 2: Lightest" in sent and "asking about: lunch" in sent and "Poha" in sent       # it sees the chat's state
    n = owner_nlu(FakeClient({"action": "dish_request", "dishes": ["not_a_dish"]}))
    assert n.owner("make me something nice", CTX)["action"] == "other"                          # invented dish: refused, rules take over
    stock = owner_nlu(FakeClient({"action": "stock", "updates": [{"item": "paneer", "qty": 0}, {"item": "unobtainium"}]}))
    assert stock.owner("we are out of paneer", CTX) == {"action": "stock", "updates": [{"item": "paneer", "qty": 0.0, "unit": "g"}]}
    ask = owner_nlu(FakeClient({"action": "ask", "text": "why is option 2 lighter?"}))
    assert ask.owner("hmm, why the khichdi one", CTX) == {"action": "ask", "text": "why is option 2 lighter?"}


def test_plain_commands_never_cost_a_model_call_and_failures_fall_back_to_rules():
    client = FakeClient({"action": "other"})
    n = owner_nlu(client)
    for plain in ("1", "1 and 2", "skip", "approve", "yes", "mode auto", "help", "fill the fridge"):
        n.owner(plain, CTX)
    assert client.calls == []
    broken = owner_nlu(FakeClient(error=RuntimeError("network down")))
    assert broken.owner("lunch dal tadka", CTX)["action"] == "meal_request" and broken.last_source == "rules"


def test_claude_answers_questions_from_the_facts_only():
    class Texty(FakeClient):
        def create(self, **kw):
            self.calls.append(kw)
            return NS(content=[NS(type="text", text="Spinach first: it goes off in 2 days.")])
    client = Texty()
    n = owner_nlu(client)
    assert n.answer("what should I eat first?", "- spinach: 300 g, eat within 2 day(s)") == "Spinach first: it goes off in 2 days."
    sent = client.calls[0]
    assert "ONLY the FACTS" in sent["system"] and "spinach: 300 g" in sent["messages"][0]["content"]
    assert NLU(None).answer("anything", "facts") is None                      # no key: the agent answers from rules
    assert owner_nlu(FakeClient(error=RuntimeError("down"))).answer("q", "f") is None
