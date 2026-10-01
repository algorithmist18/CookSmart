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


def test_yes_no_only_when_pending():
    assert parse_cook("haan", {"x": 1}) == [{"type": "yes"}]
    assert parse_cook("nahi", {"x": 1}) == [{"type": "no"}]
    assert parse_cook("haan")[0]["type"] == "unknown"   # nothing to confirm


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
