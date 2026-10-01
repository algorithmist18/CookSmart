"""Static knowledge: item catalog (units, packs, fair prices, shelf life), name aliases and the recipe book.

Quantities in recipes are for 4 servings and are scaled by household size + guests.
Staples (oil, salt, spices, ghee, ginger, garlic) are deliberately NOT tracked: the agent assumes the
kitchen always has them, as in the CookSmart spec ("plans around staples it's sure of").
"""
from __future__ import annotations

import math

# item: unit, Hindi name, pack size, fair pack price (INR), shelf life in days (None = non-perishable)
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
    "egg": dict(unit="pcs", hi="अंडा", pack=6, price=60, shelf=10),
    "chicken": dict(unit="g", hi="चिकन", pack=500, price=180, shelf=2),
    "bhindi": dict(unit="g", hi="भिंडी", pack=250, price=30, shelf=3),
    "brinjal": dict(unit="g", hi="बैंगन", pack=500, price=40, shelf=5),
    "cabbage": dict(unit="g", hi="पत्तागोभी", pack=500, price=25, shelf=7),
    "carrot": dict(unit="g", hi="गाजर", pack=500, price=40, shelf=10),
    "beans": dict(unit="g", hi="फली", pack=250, price=30, shelf=4),
    "capsicum": dict(unit="pcs", hi="शिमला मिर्च", pack=3, price=30, shelf=6),
    "lauki": dict(unit="g", hi="लौकी", pack=500, price=30, shelf=5),
    "mushroom": dict(unit="g", hi="मशरूम", pack=200, price=50, shelf=3),
    "moong": dict(unit="g", hi="मूंग", pack=500, price=80, shelf=None),
    "masoor": dict(unit="g", hi="मसूर", pack=500, price=70, shelf=None),
    "chana": dict(unit="g", hi="छोले", pack=500, price=85, shelf=None),
    "besan": dict(unit="g", hi="बेसन", pack=500, price=60, shelf=None),
    "poha": dict(unit="g", hi="पोहा", pack=500, price=45, shelf=None),
    "suji": dict(unit="g", hi="सूजी", pack=500, price=40, shelf=None),
    "bread": dict(unit="pcs", hi="ब्रेड", pack=8, price=40, shelf=4),
    "sabudana": dict(unit="g", hi="साबूदाना", pack=500, price=70, shelf=None),
    "kuttu": dict(unit="g", hi="कुट्टू", pack=500, price=80, shelf=None),
    "samak": dict(unit="g", hi="समा चावल", pack=500, price=90, shelf=None),
    "peanuts": dict(unit="g", hi="मूंगफली", pack=500, price=90, shelf=None),
    "banana": dict(unit="pcs", hi="केला", pack=6, price=40, shelf=4),
    "apple": dict(unit="pcs", hi="सेब", pack=4, price=80, shelf=8),
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
    "egg": ["egg", "eggs", "anda", "ande", "अंडा", "अंडे"],
    "chicken": ["chicken", "murgi", "चिकन", "मुर्गी"],
    "bhindi": ["bhindi", "okra", "ladyfinger", "भिंडी"],
    "brinjal": ["brinjal", "baingan", "eggplant", "aubergine", "बैंगन"],
    "cabbage": ["cabbage", "pattagobhi", "पत्तागोभी"],
    "carrot": ["carrot", "carrots", "gajar", "गाजर"],
    "beans": ["beans", "fali", "phali", "फली"],
    "capsicum": ["capsicum", "shimla", "शिमला"],
    "lauki": ["lauki", "ghiya", "dudhi", "लौकी"],
    "mushroom": ["mushroom", "mushrooms", "khumbi", "मशरूम"],
    "moong": ["moong", "mung", "मूंग"],
    "masoor": ["masoor", "मसूर"],
    "chana": ["chana", "chole", "chickpeas", "छोले", "चना"],
    "besan": ["besan", "बेसन"],
    "poha": ["poha", "पोहा"],
    "suji": ["suji", "sooji", "rava", "semolina", "सूजी"],
    "bread": ["bread", "ब्रेड"],
    "sabudana": ["sabudana", "साबूदाना"],
    "kuttu": ["kuttu", "कुट्टू"],
    "samak": ["samak", "समा"],
    "peanuts": ["peanut", "peanuts", "moongfali", "मूंगफली"],
    "banana": ["banana", "bananas", "kela", "केला"],
    "apple": ["apple", "apples", "seb", "सेब"],
}

DAIRY = {"milk", "curd", "paneer", "cream"}

# Allergen groups over the ingredients CookSmart tracks. Hidden sources matter: besan IS chickpea, bread IS wheat.
ALLERGENS: dict[str, dict] = {
    "peanut": dict(items={"peanuts"}, hi="मूंगफली (पीनट)", aliases=["peanut", "peanuts", "moongfali", "मूंगफली"]),
    "dairy": dict(items=set(DAIRY), hi="मिल्क और मिल्क प्रोडक्ट्स (दही, पनीर, क्रीम)",
                  aliases=["dairy", "milk", "doodh", "lactose", "दूध"]),
    "egg": dict(items={"egg"}, hi="अंडा", aliases=["egg", "eggs", "anda", "अंडा"]),
    "gluten": dict(items={"atta", "suji", "bread"}, hi="गेहूं (आटा, सूजी, ब्रेड)",
                   aliases=["gluten", "wheat", "gehun", "गेहूं"]),
    "chickpea": dict(items={"besan", "chana"}, hi="चना (बेसन, छोले)", aliases=["chickpea", "chana", "besan", "छोले"]),
}
JAIN_BANNED = {"onion", "potato", "carrot"}      # root vegetables
MEAT = {"chicken"}


def _r(name, hi, needs, course, prep, diet="veg", tools=("stove",), tags=()):
    return dict(name=name, hi=hi, course=course, prep=prep, diet=diet, tools=set(tools),
                stove="stove" in tools, tags=set(tags),
                needs={k: (v, ITEMS[k]["unit"]) for k, v in needs.items()})


# course: sabzi | dal | carb | one_pot | breakfast | side | vrat
# diet: veg | egg | nonveg     tools: stove | cooker | tawa | (none = no cooking)
RECIPES: dict[str, dict] = {r_id: r for r_id, r in {
    # ---- sabzi
    "palak_paneer": _r("Palak Paneer", "पालक पनीर", {"spinach": 300, "paneer": 200, "onion": 1, "tomato": 1, "cream": 50}, "sabzi", 40, tags={"heavy"}),
    "matar_paneer": _r("Matar Paneer", "मटर पनीर", {"peas": 200, "paneer": 200, "onion": 2, "tomato": 2}, "sabzi", 35),
    "paneer_bhurji": _r("Paneer Bhurji", "पनीर भुर्जी", {"paneer": 200, "onion": 1, "tomato": 2}, "sabzi", 20, tags={"quick"}),
    "aloo_gobi": _r("Aloo Gobi", "आलू गोभी", {"potato": 3, "cauliflower": 400, "tomato": 1, "onion": 1}, "sabzi", 35),
    "aloo_jeera": _r("Aloo Jeera", "आलू जीरा", {"potato": 4}, "sabzi", 20, tags={"quick", "vrat"}),
    "bhindi_masala": _r("Bhindi Masala", "भिंडी मसाला", {"bhindi": 400, "onion": 2, "tomato": 1}, "sabzi", 30),
    "baingan_bharta": _r("Baingan Bharta", "बैंगन भर्ता", {"brinjal": 500, "onion": 2, "tomato": 2}, "sabzi", 40),
    "cabbage_sabzi": _r("Cabbage Sabzi", "पत्तागोभी की सब्ज़ी", {"cabbage": 400, "potato": 1}, "sabzi", 25, tags={"light"}),
    "gajar_matar": _r("Gajar Matar", "गाजर मटर", {"carrot": 300, "peas": 150}, "sabzi", 25, tags={"light"}),
    "lauki_sabzi": _r("Lauki Sabzi", "लौकी की सब्ज़ी", {"lauki": 500, "tomato": 1}, "sabzi", 30, tags={"light"}),
    "beans_aloo": _r("Beans Aloo", "फली आलू", {"beans": 300, "potato": 2}, "sabzi", 30),
    "mix_veg": _r("Mix Veg", "मिक्स वेज", {"carrot": 150, "beans": 150, "peas": 100, "cauliflower": 200, "tomato": 1}, "sabzi", 35, tags={"light"}),
    "mushroom_masala": _r("Mushroom Masala", "मशरूम मसाला", {"mushroom": 250, "onion": 1, "tomato": 2}, "sabzi", 25),
    "shimla_aloo": _r("Shimla Mirch Aloo", "शिमला आलू", {"capsicum": 2, "potato": 2}, "sabzi", 25),
    "egg_bhurji": _r("Egg Bhurji", "अंडा भुर्जी", {"egg": 6, "onion": 1, "tomato": 1}, "sabzi", 15, diet="egg", tags={"quick"}),
    "egg_curry": _r("Egg Curry", "अंडा करी", {"egg": 6, "onion": 2, "tomato": 2}, "sabzi", 35, diet="egg"),
    "chicken_curry": _r("Chicken Curry", "चिकन करी", {"chicken": 500, "onion": 2, "tomato": 2}, "sabzi", 50, diet="nonveg", tags={"heavy"}),
    # ---- dal
    "dal_tadka": _r("Dal Tadka", "दाल तड़का", {"dal": 150, "onion": 1, "tomato": 1}, "dal", 30, tools=("stove", "cooker"), tags={"light"}),
    "tomato_dal": _r("Tomato Dal", "टमाटर दाल", {"dal": 150, "tomato": 3, "onion": 1}, "dal", 35, tools=("stove", "cooker"), tags={"light"}),
    "palak_dal": _r("Palak Dal", "पालक दाल", {"dal": 150, "spinach": 250, "onion": 1}, "dal", 35, tools=("stove", "cooker"), tags={"light"}),
    "moong_dal": _r("Moong Dal", "मूंग दाल", {"moong": 150, "tomato": 1}, "dal", 25, tools=("stove", "cooker"), tags={"light", "quick"}),
    "masoor_dal": _r("Masoor Dal", "मसूर दाल", {"masoor": 150, "onion": 1, "tomato": 1}, "dal", 25, tools=("stove", "cooker"), tags={"light"}),
    "chole": _r("Chole", "छोले", {"chana": 200, "onion": 2, "tomato": 2}, "dal", 60, tools=("stove", "cooker"), tags={"heavy"}),
    "rajma": _r("Rajma Masala", "राजमा मसाला", {"rajma": 200, "onion": 2, "tomato": 2}, "dal", 60, tools=("stove", "cooker"), tags={"heavy"}),
    "kadhi": _r("Kadhi", "कढ़ी", {"curd": 300, "besan": 60}, "dal", 30),
    # ---- carb
    "roti": _r("Roti", "रोटी", {"atta": 300}, "carb", 25, tools=("stove", "tawa")),
    "jeera_rice": _r("Jeera Rice", "जीरा चावल", {"rice": 250}, "carb", 20, tools=("stove", "cooker")),
    # ---- one pot
    "veg_pulao": _r("Veg Pulao", "वेज पुलाव", {"rice": 250, "peas": 100, "onion": 1}, "one_pot", 35, tools=("stove", "cooker")),
    "moong_khichdi": _r("Moong Khichdi", "मूंग खिचड़ी", {"rice": 150, "moong": 100}, "one_pot", 30, tools=("stove", "cooker"), tags={"light"}),
    "rajma_chawal": _r("Rajma Chawal", "राजमा चावल", {"rajma": 200, "rice": 200, "onion": 2, "tomato": 2}, "one_pot", 60, tools=("stove", "cooker"), tags={"heavy"}),
    "curd_rice": _r("Curd Rice", "दही चावल", {"rice": 200, "curd": 250}, "one_pot", 20, tools=("stove", "cooker"), tags={"light"}),
    "veg_biryani": _r("Veg Biryani", "वेज बिरयानी", {"rice": 300, "curd": 100, "carrot": 100, "peas": 100, "onion": 2}, "one_pot", 55, tools=("stove", "cooker"), tags={"heavy"}),
    # ---- breakfast / tiffin
    "poha": _r("Poha", "पोहा", {"poha": 250, "onion": 1, "peanuts": 30}, "breakfast", 15, tags={"quick", "light"}),
    "upma": _r("Upma", "उपमा", {"suji": 200, "onion": 1, "peas": 50}, "breakfast", 20, tags={"quick", "light"}),
    "besan_chilla": _r("Besan Chilla", "बेसन चीला", {"besan": 200, "onion": 1, "tomato": 1}, "breakfast", 20, tools=("stove", "tawa"), tags={"quick", "light"}),
    "aloo_paratha": _r("Aloo Paratha", "आलू पराठा", {"atta": 300, "potato": 3, "curd": 100}, "breakfast", 40, tools=("stove", "tawa"), tags={"heavy"}),
    "bread_omelette": _r("Bread Omelette", "ब्रेड ऑमलेट", {"egg": 4, "bread": 4, "onion": 1}, "breakfast", 15, diet="egg", tools=("stove", "tawa"), tags={"quick"}),
    "veg_sandwich": _r("Veg Sandwich", "वेज सैंडविच", {"bread": 8, "cucumber": 1, "tomato": 1, "onion": 1}, "breakfast", 10, tools=(), tags={"quick", "light"}),
    # ---- sides / no-cook
    "kheera_raita": _r("Kheera Raita", "खीरा रायता", {"curd": 250, "cucumber": 2}, "side", 10, tools=(), tags={"quick", "light", "vrat"}),
    "tomato_onion_salad": _r("Tomato Onion Salad", "टमाटर प्याज सलाद", {"tomato": 2, "onion": 1, "cucumber": 1}, "side", 10, tools=(), tags={"quick", "light"}),
    "sprouts_chaat": _r("Sprouts Chaat", "स्प्राउट्स चाट", {"moong": 100, "tomato": 1, "onion": 1}, "side", 10, tools=(), tags={"quick", "light"}),
    "fruit_chaat": _r("Fruit Chaat", "फ्रूट चाट", {"banana": 2, "apple": 2}, "side", 10, tools=(), tags={"quick", "light", "vrat"}),
    # ---- vrat (fasting)
    "sabudana_khichdi": _r("Sabudana Khichdi", "साबूदाना खिचड़ी", {"sabudana": 200, "potato": 2, "peanuts": 50}, "vrat", 25, tags={"vrat"}),
    "kuttu_puri": _r("Kuttu Puri", "कुट्टू की पूरी", {"kuttu": 300, "potato": 3}, "vrat", 40, tags={"vrat", "heavy"}),
    "samak_pulao": _r("Samak Pulao", "समा के चावल", {"samak": 200, "potato": 1, "peanuts": 30}, "vrat", 25, tags={"vrat", "light"}),
    "dahi_aloo": _r("Dahi Aloo", "दही आलू", {"curd": 250, "potato": 3}, "vrat", 25, tags={"vrat"}),
}.items()}

UNIT_HI = {"g": "ग्राम", "ml": "मि.ली.", "pcs": ""}


def canonical_unit(item: str) -> str:
    return ITEMS[item]["unit"]


def scale_qty(qty: float, unit: str, scale: float) -> float:
    """Scale a 4-serving quantity. Whole pieces round up; grams/ml round up to the next 10."""
    q = qty * scale
    if abs(scale - 1.0) < 1e-9:
        return float(qty)
    return float(math.ceil(q - 1e-9)) if unit == "pcs" else float(math.ceil(q / 10 - 1e-9) * 10)


def fmt_qty(qty: float, unit: str) -> str:
    q = int(qty) if float(qty).is_integer() else round(qty, 1)
    return f"{q} {unit}"
