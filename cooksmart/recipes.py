"""Static knowledge: recipe book, item catalog (units, packs, fair prices, shelf life) and name aliases.

Staples (oil, salt, spices, ghee) are deliberately NOT tracked: the agent assumes the kitchen always
has them, as in the CookSmart spec ("plans around staples it's sure of").
"""
from __future__ import annotations

# item -> unit (canonical), Hindi name, pack size, fair pack price (INR), shelf life in days (None = non-perishable)
ITEMS: dict[str, dict] = {
    "tomato": dict(unit="pcs", hi="टमाटर", pack=6, price=30, shelf=5),
    "onion": dict(unit="pcs", hi="प्याज", pack=6, price=36, shelf=20),
    "potato": dict(unit="pcs", hi="आलू", pack=6, price=30, shelf=20),
    "spinach": dict(unit="g", hi="पालक", pack=250, price=25, shelf=3),
    "paneer": dict(unit="g", hi="पनीर", pack=200, price=90, shelf=5),
    "cauliflower": dict(unit="g", hi="गोभी", pack=500, price=50, shelf=5),
    "peas": dict(unit="g", hi="मटर", pack=250, price=45, shelf=6),
    "dal": dict(unit="g", hi="दाल", pack=500, price=85, shelf=None),
    "rice": dict(unit="g", hi="चावल", pack=1000, price=80, shelf=None),
    "atta": dict(unit="g", hi="आटा", pack=1000, price=55, shelf=None),
    "curd": dict(unit="g", hi="दही", pack=400, price=40, shelf=5),
    "cream": dict(unit="ml", hi="क्रीम", pack=200, price=70, shelf=7),
    "rajma": dict(unit="g", hi="राजमा", pack=500, price=95, shelf=None),
    "cucumber": dict(unit="pcs", hi="खीरा", pack=3, price=30, shelf=5),
    "milk": dict(unit="ml", hi="दूध", pack=500, price=30, shelf=3),
}

ALIASES: dict[str, list[str]] = {
    "tomato": ["tomato", "tomatoes", "tamatar", "टमाटर"],
    "onion": ["onion", "onions", "pyaz", "pyaaz", "pyaj", "प्याज"],
    "potato": ["potato", "potatoes", "aloo", "alu", "आलू"],
    "spinach": ["spinach", "palak", "पालक"],
    "paneer": ["paneer", "पनीर"],
    "cauliflower": ["cauliflower", "gobi", "gobhi", "phoolgobhi", "गोभी", "फूलगोभी"],
    "peas": ["peas", "matar", "मटर"],
    "dal": ["dal", "daal", "toor", "दाल"],
    "rice": ["rice", "chawal", "chaawal", "चावल"],
    "atta": ["atta", "flour", "आटा"],
    "curd": ["curd", "dahi", "yogurt", "yoghurt", "दही"],
    "cream": ["cream", "malai", "क्रीम"],
    "rajma": ["rajma", "राजमा"],
    "cucumber": ["cucumber", "kheera", "khira", "खीरा"],
    "milk": ["milk", "doodh", "dudh", "दूध"],
}

# id -> recipe. needs: item -> (qty, unit). stove: needs the stove. prep: minutes.
RECIPES: dict[str, dict] = {
    "palak_paneer": dict(
        name="Palak Paneer", hi="पालक पनीर", stove=True, prep=40,
        needs={"spinach": (300, "g"), "paneer": (200, "g"), "onion": (1, "pcs"),
               "tomato": (1, "pcs"), "cream": (50, "ml")}),
    "tomato_dal": dict(
        name="Tomato Dal", hi="टमाटर दाल", stove=True, prep=35,
        needs={"dal": (150, "g"), "tomato": (3, "pcs"), "onion": (1, "pcs")}),
    "aloo_gobi": dict(
        name="Aloo Gobi", hi="आलू गोभी", stove=True, prep=35,
        needs={"potato": (3, "pcs"), "cauliflower": (400, "g"), "tomato": (1, "pcs"),
               "onion": (1, "pcs")}),
    "rajma_chawal": dict(
        name="Rajma Chawal", hi="राजमा चावल", stove=True, prep=60,
        needs={"rajma": (200, "g"), "rice": (200, "g"), "onion": (2, "pcs"), "tomato": (2, "pcs")}),
    "matar_paneer": dict(
        name="Matar Paneer", hi="मटर पनीर", stove=True, prep=35,
        needs={"peas": (200, "g"), "paneer": (200, "g"), "onion": (2, "pcs"), "tomato": (2, "pcs")}),
    "dal_tadka": dict(
        name="Dal Tadka", hi="दाल तड़का", stove=True, prep=30,
        needs={"dal": (150, "g"), "onion": (1, "pcs"), "tomato": (1, "pcs")}),
    "veg_pulao": dict(
        name="Veg Pulao", hi="वेज पुलाव", stove=True, prep=35,
        needs={"rice": (250, "g"), "peas": (100, "g"), "onion": (1, "pcs")}),
    "aloo_paratha": dict(
        name="Aloo Paratha", hi="आलू पराठा", stove=True, prep=40,
        needs={"atta": (300, "g"), "potato": (3, "pcs"), "curd": (100, "g")}),
    "palak_dal": dict(
        name="Palak Dal", hi="पालक दाल", stove=True, prep=35,
        needs={"dal": (150, "g"), "spinach": (250, "g"), "onion": (1, "pcs")}),
    "curd_rice": dict(
        name="Curd Rice", hi="दही चावल", stove=True, prep=20,
        needs={"rice": (200, "g"), "curd": (250, "g")}),
    "paneer_bhurji": dict(
        name="Paneer Bhurji", hi="पनीर भुर्जी", stove=True, prep=20,
        needs={"paneer": (200, "g"), "onion": (1, "pcs"), "tomato": (2, "pcs")}),
    "kheera_raita": dict(
        name="Kheera Raita", hi="खीरा रायता", stove=False, prep=10,
        needs={"curd": (250, "g"), "cucumber": (2, "pcs")}),
    "tomato_onion_salad": dict(
        name="Tomato Onion Salad", hi="टमाटर प्याज सलाद", stove=False, prep=10,
        needs={"tomato": (2, "pcs"), "onion": (1, "pcs"), "cucumber": (1, "pcs")}),
}

UNIT_HI = {"g": "ग्राम", "ml": "मि.ली.", "pcs": ""}


def canonical_unit(item: str) -> str:
    return ITEMS[item]["unit"]


def fmt_qty(qty: float, unit: str) -> str:
    q = int(qty) if float(qty).is_integer() else round(qty, 1)
    return f"{q} {unit}"
