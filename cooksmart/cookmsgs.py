"""Hindi message templates for the cook. The ONLY way text reaches the cook.

The cook wants one thing: what needs to be made. These templates take dish names and the cook's own
words back for confirmation; they have no parameters for money, stock levels, orders or delivery.
"""
from __future__ import annotations

from .channels import CookMessage
from .recipes import ITEMS, RECIPES, UNIT_HI

T = {
    "brief": "नमस्ते! आज बनाना है: {dishes}।",
    "brief_wait": " {wait} का सामान अभी नहीं पहुँचा है। पहले {start} शुरू करें।",
    "brief_prep": " सामान अभी नहीं पहुँचा है। तब तक कटाई-तैयारी कर लें, सामान आते ही बता दिया जाएगा।",
    "brief_end": " समझ गए? 'हाँ' बोलें।",
    "delivered": "सामान पहुँच गया है। अब {wait} भी शुरू करें।",
    "readback": "आपने कहा: {summary}। सही है? (हाँ / नहीं)",
    "ask_repeat": "आवाज़ साफ़ नहीं आई। कृपया दोबारा बोलें या लिखकर भेजें।",
    "not_understood": "समझ नहीं आया। कृपया दोबारा बताएं।",
    "noted": "ठीक है, नोट कर लिया।",
    "retry": "ठीक है, दोबारा बताएं।",
    "switch": "योजना बदली गई है। आज बनाना है: {dishes}।",
    "no_menu": "आज का मेन्यू थोड़ी देर में भेजा जाएगा।",
    "eod": "आज क्या-क्या खत्म हुआ या कितना बचा? बोलकर बता दें।",
    "thanks": "धन्यवाद! 🙏",
    "greet": "नमस्ते! 🙏 आप पहुँच जाएँ तो बता दें, मैं आज का मेन्यू भेज दूँगा।",
    "menu_repeat": "आज बनाना है: {dishes}।",
    "help": "समझ नहीं आया। आप ऐसे बोल सकते हैं: 'आ गई', 'पनीर खत्म', 'गैस खराब है', 'समय कम है', 'खाना बन गया'।",
    "leave_ok": "ठीक है, बता दिया गया है। आराम करें। 🙏",
    "great": "बहुत बढ़िया! 👍",
    "relay": "संदेश: {text}",
}

QUICK = {"readback": ("हाँ", "नहीं"), "brief_end": ("हाँ", "नहीं")}


def dish_names(recipe_ids: list[str]) -> str:
    return " और ".join(RECIPES[r]["hi"] for r in recipe_ids)


MEAL_HI = {"breakfast": "ब्रेकफास्ट", "lunch": "लंच", "dinner": "डिनर"}


def dish_names_by_meal(meals: dict) -> str | None:
    """'ब्रेकफास्ट में पोहा, लंच में … , डिनर में …' when more than one meal is planned, else None."""
    parts = [f"{MEAL_HI[m]} में {dish_names(meals[m])}" for m in ("breakfast", "lunch", "dinner") if meals.get(m)]
    return ", ".join(parts) if len(parts) > 1 else None


def render(key: str, lang: str = "hi-IN", **kw) -> CookMessage:
    return CookMessage(T[key].format(**kw), lang, QUICK.get(key, ()))


def concat(*parts: CookMessage) -> CookMessage:
    return CookMessage("".join(p.text for p in parts), parts[0].lang, parts[-1].buttons)


def summarize_intents(intents: list[dict]) -> str:
    """Read the cook's own report back to them, in Hindi, for confirmation."""
    bits = []
    for i in intents:
        t = i["type"]
        hi = ITEMS[i["item"]]["hi"] if i.get("item") else ""
        if t == "used_up":
            bits.append(f"{hi} खत्म हो गया")
        elif t == "remaining":
            q = int(i["qty"]) if float(i["qty"]).is_integer() else i["qty"]
            bits.append(f"{hi} {q} {UNIT_HI.get(i['unit'], '')} बचा है".replace("  ", " "))
        elif t == "low":
            bits.append(f"{hi} कम है")
        elif t == "spoiled":
            bits.append(f"{hi} खराब हो गया")
        elif t == "cannot_cook":
            bits.append("गैस/चूल्हा खराब है" if i.get("reason") == "stove" else
                        "कुकर खराब है" if i.get("reason") == "cooker" else
                        "आज समय कम है" if i.get("reason") == "time" else "आज बनाने में दिक्कत है")
    return "; ".join(bits)
