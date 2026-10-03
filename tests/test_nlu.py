from cooksmart.nlu import parse_cook, parse_owner


def types(text, pending=None):
    return [(i["type"], i.get("item"), i.get("qty")) for i in parse_cook(text, pending)]


def test_hinglish_used_up_and_remaining():
    assert types("paneer poora lag gaya, 2 tamatar bache") == [("used_up", "paneer", None),
                                                               ("remaining", "tomato", 2.0)]


def test_devanagari():
    assert types("पनीर खत्म हो गया") == [("used_up", "paneer", None)]
    assert types("२ टमाटर बचे") == [("remaining", "tomato", 2.0)]


def test_units_normalised():
    assert types("paneer 100 gram bacha") == [("remaining", "paneer", 100.0)]
    assert types("doodh 1 litre bacha") == [("remaining", "milk", 1000.0)]


def test_problems():
    assert parse_cook("gas kharab hai")[0] == {"type": "cannot_cook", "reason": "stove"}
    assert parse_cook("आज time nahi hai")[0] == {"type": "cannot_cook", "reason": "time"}


def test_short_yes_no_always_understood():
    # the brief ends with "samajh gaye? haan bolen", so a bare yes/no must work with nothing pending
    assert parse_cook("haan") == [{"type": "yes"}]
    assert parse_cook("हाँ") == [{"type": "yes"}]
    assert parse_cook("nahi", {"x": 1}) == [{"type": "no"}]
    assert parse_cook("haan, aa gayi")[0]["type"] == "arrived"   # a yes inside another phrase isn't a bare yes


def test_unknown_item_never_invented():
    assert parse_cook("kuch bhi")[0]["type"] == "unknown"


def test_owner_parsing():
    assert parse_owner("1 and 2") == {"action": "choose", "choices": [1, 2]}
    assert parse_owner("mode auto") == {"action": "mode", "mode": "auto"}
    assert parse_owner("cap 300") == {"action": "cap", "cap": 300}
    assert parse_owner("I want rajma chawal")["action"] == "dish_request"
    assert parse_owner("cream 100 ml") == {"action": "stock",
                                           "updates": [{"item": "cream", "qty": 100.0, "unit": "ml"}]}
    assert parse_owner("no tomatoes")["updates"][0]["qty"] == 0.0
    assert parse_owner("approve")["action"] == "yes"
    assert parse_owner("No, hold it")["action"] == "no"
    assert parse_owner("something lighter")["action"] == "other"


# ------------------------------------------------------------------ looser, more natural owner messages
import pytest as _pytest
from cooksmart.nlu import parse_owner as _po

LOOSE = [
    ("i'll have poha for breakfast", {"action": "meal_request", "breakfast": ["poha"], "lunch": [], "dinner": []}),
    ("poha for breakfast and dal rice for lunch", {"action": "meal_request", "breakfast": ["poha"], "lunch": ["dal_tadka", "jeera_rice"], "dinner": []}),
    ("I want pallak panner for lunch and poha in the morning", {"action": "meal_request", "breakfast": ["poha"], "lunch": ["palak_paneer"], "dinner": []}),
    ("naashte me poha", {"action": "meal_request", "breakfast": ["poha"], "lunch": [], "dinner": []}),
    ("dinner mein khichdi", {"action": "meal_request", "breakfast": [], "lunch": [], "dinner": ["moong_khichdi"]}),
    ("khichdi for dinner", {"action": "meal_request", "breakfast": [], "lunch": [], "dinner": ["moong_khichdi"]}),
    ("kal dal chawal banao", {"action": "dish_request", "dishes": ["dal_tadka", "jeera_rice"]}),
    ("nothing for lunch", {"action": "skip", "meal": "lunch"}),
    ("no breakfast today", {"action": "skip", "meal": "breakfast"}),
    ("skip dinner", {"action": "skip", "meal": "dinner"}),
    ("skip", {"action": "skip"}),
    ("sounds good", {"action": "yes"}), ("book it", {"action": "yes"}), ("place the order", {"action": "yes"}),
    ("haan kar do", {"action": "yes"}), ("go ahead", {"action": "yes"}),
    ("don't order", {"action": "no", "text": "don't order"}), ("cancel", {"action": "no", "text": "cancel"}),
    ("not now", {"action": "no", "text": "not now"}),
    ("2 looks good", {"action": "choose", "choices": [2]}), ("go with 2", {"action": "choose", "choices": [2]}),
    ("i'll take the first", {"action": "choose", "choices": [1]}), ("number 3", {"action": "choose", "choices": [3]}),
    ("we have guests tomorrow, 5 people", {"action": "flags", "flags": {"guests": 5}}),
    ("tomatoes are over", {"action": "stock", "updates": [{"item": "tomato", "qty": 0.0, "unit": "pcs"}]}),
    ("the spinach went bad", {"action": "stock", "updates": [{"item": "spinach", "qty": 0.0, "unit": "g"}]}),
    ("no tomatoes", {"action": "stock", "updates": [{"item": "tomato", "qty": 0.0, "unit": "pcs"}]}),
    ("no onion in it", {"action": "other", "text": "no onion in it"}),                       # a wish about the dish, not a stock report
    ("can you make it quicker", {"action": "other", "text": "can you make it quicker"}),     # a request, not a question
    ("thanks", {"action": "chat", "kind": "thanks"}), ("good night", {"action": "chat", "kind": "night"}),
    ("hold on", {"action": "chat", "kind": "pause"}), ("hi", {"action": "chat", "kind": "hello"}),
    ("what should I eat first?", {"action": "ask", "text": "what should I eat first?"}),
]


@_pytest.mark.parametrize("text,expected", LOOSE, ids=[t for t, _ in LOOSE])
def test_natural_phrasing_is_understood(text, expected):
    assert _po(text) == expected
