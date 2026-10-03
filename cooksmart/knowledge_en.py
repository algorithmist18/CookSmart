"""English counterpart of knowledge.py: the same guidance for the same items, in plain English.

Used for the English half of the knowledge base (the agent speaks Hindi, but the owner, a new cook or a different
voice agent may work in English, and retrieval is better when both languages are present). Same rules: general
nutrition, never medical advice, never a person's condition.
"""
from __future__ import annotations

from .recipes import ITEMS

_DRY = dict(store="In an airtight container, in a cool dry place", lasts="Several months",
            spoil="Insects or webbing, damp, or an odd smell. If so, throw away that part and tell Madam/Sir",
            use_up="", taste="")


def _dry(**kw):
    return {**_DRY, **kw}


ITEM_CARE_EN: dict[str, dict] = {
    "tomato": dict(store="At room temperature away from sun; in the fridge if very ripe", lasts="3-5 days",
                   spoil="Mould, leaking juice, sour smell. Throw away",
                   use_up="Puree over-ripe tomatoes and add to dal or gravy",
                   taste="Very ripe tomatoes are sweet and juicy, best in dal, gravy and chutney; use firm ones for salad",
                   health="Vitamin C and lycopene"),
    "onion": dict(store="In a dry, airy place; not next to potatoes", lasts="2-3 weeks",
                  spoil="Wet, very soft, black mould or smell. Cut away and discard the rotten part",
                  use_up="A little sprouting is fine if the onion is firm and does not smell",
                  taste="Well-cooked onion adds sweetness to gravy", health="Adds flavour; some fibre"),
    "potato": dict(store="In a dark, cool, dry place; away from onions", lasts="2-3 weeks",
                   spoil="Green colour, heavy sprouting, soft or rotten",
                   use_up="Do not eat green parts or heavily sprouted potatoes (can be harmful); cut light sprouts out completely",
                   taste="Older potatoes suit paratha and stuffing; new potatoes suit jeera aloo",
                   health="Energy and potassium; better boiled or roasted than fried"),
    "spinach": dict(store="Unwashed, wrapped in paper, in the fridge", lasts="2-3 days",
                    spoil="Yellowing, sliminess, smell. Throw away",
                    use_up="If wilted but not slimy, blanch and cook it today",
                    taste="Fresh spinach is greenest and sweetest; if wilted, blanch and do not overcook",
                    health="Iron, folate and vitamin K"),
    "paneer": dict(store="In the fridge, submerged in water (change the water daily)", lasts="3-5 days once opened, or until the pack date",
                   spoil="Sour smell, sliminess, yellow film. Throw away",
                   use_up="Paneer that has firmed up: soak in warm water for 10 minutes to soften; use in bhurji or gravy",
                   taste="Older paneer is better in bhurji or gravy than fried; add paneer last so it stays soft",
                   health="Protein and calcium"),
    "cauliflower": dict(store="In the fridge, kept dry", lasts="4-5 days", spoil="Spreading black spots, sliminess, smell",
                        use_up="Cut off small dark spots; stalks and soft leaves can go in the sabzi too",
                        taste="Fresh gobhi is crisp when roasted; slightly older is good in gravy or paratha stuffing",
                        health="Fibre and vitamin C"),
    "peas": dict(store="In the fridge; in the freezer if you have a lot", lasts="5-6 days fresh, months frozen",
                 spoil="Sliminess, smell, mould", use_up="If you have a lot, boil and freeze",
                 taste="Fresh peas are sweet; do not overcook", health="Protein and fibre"),
    "dal": _dry(health="Protein and fibre"),
    "rice": _dry(health="Gives energy; serve with dal and sabzi"),
    "atta": _dry(lasts="2-3 months", health="Fibre; coarsely ground atta is better"),
    "curd": dict(store="In the fridge", lasts="5-7 days", spoil="Mould, pink or green film, bitter smell. Throw away",
                 use_up="If sour but not mouldy, use in kadhi, marinades or paratha dough",
                 taste="Sour curd is best for kadhi; fresh curd for raita and curd rice", health="Good for digestion; calcium"),
    "cream": dict(store="In the fridge", lasts="3-4 days once opened", spoil="Sour smell, curdled. Throw away",
                  use_up="Use a small amount in palak or paneer gravy", taste="Add at the end, do not boil",
                  health="Rich, so keep the quantity small"),
    "rajma": _dry(health="Protein and fibre; soak overnight and boil well"),
    "cucumber": dict(store="In the fridge", lasts="4-5 days", spoil="Very soft, slimy, bitter. Throw away if bitter",
                     use_up="If soft, remove the seeds and use in raita", taste="Firm cucumber in salad; soft in raita",
                     health="Lots of water, cooling"),
    "milk": dict(store="Boiled, in the fridge", lasts="1-2 days after boiling", spoil="Curdling, sour smell",
                 use_up="Split milk can make home-made paneer, but throw it away if it smells", taste="", health="Calcium"),
    "egg": dict(store="In the fridge", lasts="3-4 weeks", spoil="Smell when cracked; floats in water if very old",
                use_up="Cook old eggs thoroughly", taste="", health="Protein; always fully cooked"),
    "chicken": dict(store="In the coldest part of the fridge, in a separate box", lasts="1-2 days",
                    spoil="Smell, sliminess, green-grey colour",
                    use_up="Do not use after the pack expiry date. Throw it away. Wash utensils and board used for raw chicken separately and cook it thoroughly",
                    taste="Fresh chicken cooks quickly; do not overcook", health="Protein; lighter without the skin"),
    "bhindi": dict(store="Dry, in cloth or paper; do not keep wet", lasts="2-3 days", spoil="Sliminess, black spots, soft",
                   use_up="If it has gone soft, cook it today", taste="Wash, dry completely and then cut: less sticky",
                   health="Fibre"),
    "brinjal": dict(store="In a cool place or the fridge", lasts="4-5 days", spoil="Wrinkled, soft rotten spots",
                    use_up="Cut off small spots", taste="Roast for bharta; fresh brinjal has fewer seeds", health="Fibre"),
    "cabbage": dict(store="In the fridge", lasts="1 week", spoil="Rotten smell, slimy leaves",
                    use_up="Remove spoiled outer leaves", taste="Cook lightly to keep some crunch", health="Fibre and vitamin C"),
    "carrot": dict(store="In the fridge", lasts="1-2 weeks", spoil="Mould, sliminess",
                   use_up="If rubbery, soak in cold water for 30 minutes to crisp up", taste="Sweet; goes well with peas",
                   health="Vitamin A (beta-carotene)"),
    "beans": dict(store="In the fridge", lasts="3-4 days", spoil="Sliminess, black spots", use_up="Remove strings from older beans",
                  taste="Do not overcook", health="Fibre"),
    "capsicum": dict(store="In the fridge", lasts="5-6 days", spoil="Very soft, black spots", use_up="If wrinkled, cook today",
                     taste="Add last to keep it crisp", health="Vitamin C"),
    "lauki": dict(store="In the fridge", lasts="4-5 days", spoil="Soft rotten spots, smell",
                  use_up="Taste a small piece first. If bitter, throw the whole thing away and do not cook it (bitter lauki can be harmful)",
                  taste="A light sabzi; good with tomato", health="Light and easy to digest; lots of water"),
    "mushroom": dict(store="In a paper bag in the fridge, unwashed", lasts="2-3 days", spoil="Sliminess, black spots, smell. Throw away",
                     use_up="Cook quickly; do not eat slimy mushrooms", taste="Fry fast on high heat", health="Protein and vitamin B"),
    "moong": _dry(health="Easy-to-digest dal"),
    "masoor": _dry(health="Protein and iron"),
    "chana": _dry(health="Protein and fibre; soak and boil well"),
    "besan": _dry(lasts="2-3 months", health="Protein; heavy when fried"),
    "poha": _dry(health="Light breakfast; better with vegetables"),
    "suji": _dry(lasts="2-3 months", health="Light; add vegetables"),
    "bread": dict(store="In a dry place, not the fridge", lasts="3-4 days",
                  spoil="Green or white mould. Check the whole pack and throw it away",
                  use_up="Day-old bread (no mould) makes toast, upma or bread pakora", taste="Day-old bread is crisp when toasted",
                  health="Whole wheat is better than maida"),
    "sabudana": _dry(health="Gives energy, low in protein: serve with peanuts or curd"),
    "kuttu": _dry(lasts="1-2 months", health="Allowed in vrat; light to digest"),
    "samak": _dry(health="Allowed in vrat; light"),
    "peanuts": _dry(health="Protein and good fat, but never if there is a peanut allergy"),
    "banana": dict(store="At room temperature", lasts="3-4 days", spoil="Very black, leaking juice, smell",
                   use_up="Very ripe bananas: paratha, shake or halwa", taste="Ripe bananas are sweet and best in sweet dishes",
                   health="Energy and potassium"),
    "apple": dict(store="In the fridge", lasts="1-2 weeks", spoil="Soft rotten spots, mould", use_up="Cut out soft spots",
                  taste="Firm apple in chaat", health="Fibre"),
}
ITEM_CARE_EN = {k: {**dict(store="", lasts="", spoil="", use_up="", taste="", health=""), **v} for k, v in ITEM_CARE_EN.items()}
assert set(ITEM_CARE_EN) == set(ITEMS), set(ITEMS) ^ set(ITEM_CARE_EN)

DISH_TIPS_EN = {
    "palak_paneer": "Blanch and grind the spinach to keep it green; add less cream, at the end; cook the paneer only the last 3-4 minutes",
    "tomato_dal": "Let the tomatoes cook down fully; ripe tomatoes are best here",
    "dal_tadka": "Add the tadka last and cover immediately",
    "palak_dal": "Add the spinach last so it stays green",
    "matar_paneer": "Do not overcook the peas; paneer last",
    "aloo_gobi": "Do not stir too much or the gobhi and aloo will break",
    "bhindi_masala": "Dry the bhindi completely before cutting and do not cook it covered",
    "baingan_bharta": "Roast the brinjal directly on the flame for a smoky taste",
    "kadhi": "Sour curd is best for kadhi; keep stirring until it boils",
    "kheera_raita": "Squeeze the water out of soft cucumber",
    "poha": "Do not soak the poha too long",
    "aloo_paratha": "Cool the filling before stuffing; older potatoes are good here",
    "moong_khichdi": "Light and easy to digest, good for anyone who is unwell or elderly",
    "rajma": "Boil overnight-soaked rajma well; it must not be firm inside",
    "chole": "Boil overnight-soaked chana well; it must not be firm inside",
}

COURSE_TIPS_EN = {"sabzi": "Do not overcook the sabzi", "dal": "Keep the dal thick or thin as the family likes",
                  "one_pot": "Serve with curd or salad", "breakfast": "Serve hot", "side": "Serve cold", "carb": "",
                  "vrat": "Follow the vrat rules"}

HEALTH_EN = {
    "diabetes": "Much less sugar and sweets; less rice, potato and maida; more dal and sabzi",
    "high_bp": "Less salt; no pickle, papad or extra salt on top",
    "cholesterol": "Less ghee and oil; nothing fried; no cream",
    "weight_loss": "Less oil; nothing fried; more sabzi and dal",
    "soft_food": "Soft, well-cooked food; mild spice",
    "gas_acidity": "Mild spice; nothing very fried or heavy",
}
SPICE_EN = {"mild": "mild", "medium": "medium", "hot": "spicy"}
LEVEL_EN = {"low": "low", "normal": "normal", "high": "high"}
AGE_EN = {"child": "child", "adult": "adult", "elder": "elder"}
ALLERGEN_EN = {"peanut": "peanuts", "dairy": "milk and milk products (curd, paneer, cream)", "egg": "eggs",
               "gluten": "wheat (atta, suji, bread)", "chickpea": "chickpea (besan, chole)"}

PHRASEBOOK_EN = [
    ("Paneer khatam ho gaya", "Paneer is completely finished", "Repeat to confirm: 'Paneer is completely finished, right?' Record only after she says yes"),
    ("2 tomatoes are left", "2 tomatoes remain", "Repeat: 'Two tomatoes left, right?'"),
    ("Tomatoes are low", "Low, amount unknown", "Ask 'Roughly how many are left?'; if she cannot say, record 'low'"),
    ("Gas is not burning / cylinder finished", "The stove is not working",
     "First ask 'Is there a smell of gas?' (if yes, emergency steps); then offer a no-stove option"),
    ("The cooker is broken", "The pressure cooker is not working", "Give a menu that needs no cooker"),
    ("There is little time today", "Needs a quick dish", "Offer an option under 30 minutes"),
    ("The sabzi was rotten", "Vegetable is spoiled", "Ask which one; do not cook anything rotten; change the menu"),
    ("I won't come tomorrow", "Day off tomorrow", "Say okay; Madam/Sir will be alerted; do not ask why"),
    ("The food is ready", "Cooking done", "Say thanks; ask 'What was less or more today?'"),
    ("When will the money / groceries come?", "Money or delivery question", "Politely say 'Madam/Sir will tell you'"),
]
DEFAULT_UNITS_NOTE = "1 katori is about {katori} ml for this household."


def item_name(item: str) -> str:
    return item.replace("_", " ")
