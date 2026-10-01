"""Language understanding for both chats.

Rule-based parsers (Hindi in Devanagari, romanised Hinglish, English) are the always-available base.
When ANTHROPIC_API_KEY is set, Claude parses the cook's messages first and the rules are the fallback.
Either way the result is the same small structured vocabulary, validated against the item catalog.
"""
from __future__ import annotations

import json
import re

from .recipes import ALIASES, ITEMS, RECIPES

# ---------- normalisation ----------
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
TOKEN_RE = re.compile(r"[a-z0-9_.ऀ-ॿ]+")
WORD = r"(?<![a-z0-9_ऀ-ॿ]){}(?![a-z0-9_ऀ-ॿ])"


def norm(text: str) -> str:
    t = text.lower().translate(_DEV_DIGITS)
    return t.replace("़", "").replace("ँ", "ं").replace("’", "'")  # nukta, chandrabindu


def tokens(text: str) -> list[str]:
    return [t.strip(".") for t in TOKEN_RE.findall(norm(text)) if t.strip(".")]


ITEM_BY_ALIAS = {norm(a): item for item, al in ALIASES.items() for a in al}
DISH_ALIASES: dict[str, str] = {}
for _rid, _r in RECIPES.items():
    DISH_ALIASES[norm(_r["name"])] = _rid
    DISH_ALIASES[norm(_r["hi"])] = _rid
    DISH_ALIASES[_rid.replace("_", " ")] = _rid
DISH_ALIASES.update({"chicken curry": "chicken_curry", "rajma chawal": "rajma_chawal", "chole": "chole"})

YES = {"haan", "han", "ha", "haa", "ji", "sahi", "yes", "y", "ok", "okay", "theek", "thik", "correct",
       "yep", "yeah", "approve", "approved", "confirm", "हां", "हा", "जी", "सही", "ठीक"}
NO = {"nahi", "nahin", "nhi", "no", "galat", "na", "nope", "नहीं", "नही", "गलत", "decline"}
USED_UP = {"khatam", "khtm", "khatm", "finished", "over", "empty", "gone", "none", "खत्म", "खतम", "समाप्त"}
REMAINING = {"bache", "bacha", "bachi", "bachey", "left", "remaining", "बचे", "बचा", "बची"}
LOW = {"kam", "low", "कम"}
BAD = {"kharab", "band", "broken", "खराब", "बंद"}
SPOILED = {"kharab", "sad", "sada", "sadh", "spoiled", "spoilt", "rotten", "bad", "खराब", "सड़", "सड"}
STOVE = {"gas", "stove", "chulha", "cylinder", "चूल्हा", "गैस", "सिलेंडर"}
COOKER = {"cooker", "कुकर", "pressure"}
TIME = {"time", "samay", "टाइम", "समय"}
NEG = {"nahi", "nahin", "nhi", "kam", "less", "not", "नहीं", "नही", "कम"}
CONJ = {"aur", "and", "और", "phir", "फिर"}
GREET = {"namaste", "namaskar", "hello", "hi", "hii", "hey", "pranam", "morning", "gm",
         "नमस्ते", "नमस्कार", "हेलो", "हैलो", "सुप्रभात"}
GONE = {"gaya", "gayi", "gai", "gaye", "गया", "गई", "गयी", "गए"}
UNIT_WORDS = {"g": ("g", 1), "gm": ("g", 1), "gram": ("g", 1), "grams": ("g", 1), "ग्राम": ("g", 1),
              "kg": ("g", 1000), "kilo": ("g", 1000), "किलो": ("g", 1000),
              "ml": ("ml", 1), "l": ("ml", 1000), "litre": ("ml", 1000), "liter": ("ml", 1000),
              "pcs": ("pcs", 1), "pc": ("pcs", 1), "piece": ("pcs", 1), "pieces": ("pcs", 1)}
HI_NUMS = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6,
           "saat": 7, "aath": 8, "nau": 9, "das": 10, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5,
           "छह": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10}


def find_items(toks: list[str]) -> list[str]:
    seen: list[str] = []
    for t in toks:
        item = ITEM_BY_ALIAS.get(t)
        if item and item not in seen:
            seen.append(item)
    return seen


def find_number(toks: list[str]) -> float | None:
    for t in toks:
        if re.fullmatch(r"\d+(\.\d+)?", t):
            return float(t)
    for t in toks:
        if t in HI_NUMS:
            return float(HI_NUMS[t])
    return None


def find_unit(toks: list[str], item: str, qty: float | None) -> tuple[float | None, str]:
    unit = ITEMS[item]["unit"]
    for t in toks:
        if t in UNIT_WORDS:
            u, mult = UNIT_WORDS[t]
            if qty is not None:
                qty = qty * mult
            return qty, u
    return qty, unit


def _has_seq(toks: list[str], a: set[str], b: set[str]) -> bool:
    return any(toks[i] in a and toks[i + 1] in b for i in range(len(toks) - 1))


def _has_unit(toks: list[str]) -> bool:
    return any(t in UNIT_WORDS for t in toks)


def _clauses(text: str) -> list[list[str]]:
    out: list[list[str]] = []
    for part in re.split(r"[,;।\n]", norm(text)):
        cur: list[str] = []
        for t in tokens(part):
            if t in CONJ:
                if cur:
                    out.append(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            out.append(cur)
    return out


# ---------- cook ----------
def _arrived(t: list[str]) -> bool:
    s = set(t)
    return (_has_seq(t, {"aa", "आ"}, GONE) or bool({"pahunch", "pahuch", "पहुंच", "पहुच"} & s)
            or bool({"arrived", "reached", "here", "came"} & s))


def _ask_menu(t: list[str]) -> bool:
    s = set(t)
    hi = {"kya", "क्या"} & s and {"banana", "banega", "banau", "banaun", "बनाना", "बनेगा", "बनाऊं"} & s
    en = "menu" in s or ("what" in s and {"cook", "make", "today", "cooking"} & s)
    return bool(hi or en)


def _done(t: list[str]) -> bool:
    s = set(t)
    if {"done", "complete", "completed"} & s:
        return True
    return (_has_seq(t, {"ho", "हो", "ban", "bana", "बन"}, GONE)
            and bool({"khana", "kaam", "खाना", "काम", "ho", "हो", "ban", "बन", "bana"} & s))


def _leave(t: list[str]) -> bool:
    s = set(t)
    if {"chhutti", "chutti", "छुट्टी", "leave", "absent", "unwell", "sick", "bimar", "बीमार"} & s:
        return True
    can_not = {"paungi", "paunga", "sakti", "sakta", "rahi", "raha", "पाऊंगी", "पाऊंगा", "सकती", "सकता"}
    return bool((NEG & s) and ({"aa", "आ", "aaungi", "aaunga", "आऊंगी"} & s) and (can_not & s)) or \
        ("not" in s and "coming" in s) or ("cant" in s and "come" in s) or ("can't" in norm(" ".join(t)))


def parse_cook(text: str, pending: dict | None = None) -> list[dict]:
    """-> list of intents: used_up | remaining | low | spoiled | cannot_cook | yes | no | leave | done |
    arrived | ask_menu | greeting | unknown."""
    toks = tokens(text)
    # A short yes/no is always meaningful: it answers a read-back ("sahi hai?") or the brief ("samajh gaye?").
    if 0 < len(toks) <= 3 and not find_items(toks) and not (_arrived(toks) or _done(toks) or _leave(toks)):
        if any(t in YES for t in toks):
            return [{"type": "yes"}]
        if any(t in NO for t in toks):
            return [{"type": "no"}]
    intents: list[dict] = []
    for cl in _clauses(text):
        # equipment / time problems
        if any(t in STOVE for t in cl) and any(t in BAD or t in NEG or t in {"working", "empty", "khatam", "खत्म"} for t in cl):
            intents.append({"type": "cannot_cook", "reason": "stove"})
            continue
        if any(t in COOKER for t in cl) and any(t in BAD or t in NEG for t in cl):
            intents.append({"type": "cannot_cook", "reason": "cooker"})
            continue
        if any(t in TIME for t in cl) and any(t in NEG for t in cl):
            intents.append({"type": "cannot_cook", "reason": "time"})
            continue
        items = find_items(cl)
        if not items:
            continue
        qty = find_number(cl)
        for item in items:
            q, unit = find_unit(cl, item, qty)
            if any(t in REMAINING for t in cl) and q is not None:
                intents.append({"type": "remaining", "item": item, "qty": q, "unit": unit})
            elif any(t in SPOILED for t in cl):
                intents.append({"type": "spoiled", "item": item})
            elif (any(t in USED_UP for t in cl) or _has_seq(cl, NO, {"hai", "h", "है"})
                  or {"no", "out", "ran"} & set(cl)
                  or ({"poora", "पूरा", "pura"} & set(cl) and {"lag", "लग", "use", "gaya"} & set(cl))):
                intents.append({"type": "used_up", "item": item})
            elif any(t in LOW for t in cl):
                intents.append({"type": "low", "item": item})
    if intents:
        return intents
    if _leave(toks):
        return [{"type": "leave"}]
    if _done(toks):
        return [{"type": "done"}]
    if _arrived(toks):
        return [{"type": "arrived"}]
    if _ask_menu(toks):
        return [{"type": "ask_menu"}]
    if set(toks) & GREET:
        return [{"type": "greeting"}]
    return [{"type": "unknown"}]


# ---------- owner ----------
def _dishes_in(low: str) -> list[str]:
    """Every dish named in the text, in order of appearance (longest names win, no overlaps)."""
    found, text = [], low
    for alias, rid in sorted(DISH_ALIASES.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(WORD.format(re.escape(alias)), text):
            found.append((m.start(), rid))
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    out: list[str] = []
    for _, rid in sorted(found):
        if rid not in out:
            out.append(rid)
    return out


def parse_owner(text: str) -> dict:
    """-> {action: ...}. Interpretation of yes/no/choose depends on the plan state (done by the agent)."""
    toks = tokens(text)
    low = norm(text).strip()

    m = re.match(r"^(?:tell|ask|message|msg|inform)\s+(?:the\s+)?(?:cook|didi|bai|maid)\s*[:,\-]?\s*(.+)$",
                 text.strip(), re.S | re.I) \
        or re.match(r"^(?:cook|didi|bai)\s+(?:ko\s+)?(?:bolo|batao|bol do)\s*[:,\-]?\s*(.+)$",
                    text.strip(), re.S | re.I)
    if m:
        return {"action": "relay", "text": m.group(1).strip()}
    m = re.match(r"^mode\s+(auto|approve)\b", low)
    if m:
        return {"action": "mode", "mode": m.group(1)}
    m = re.match(r"^cap\s+(\d+)", low)
    if m:
        return {"action": "cap", "cap": int(m.group(1))}
    if re.match(r"^(all good|sab theek|sab sahi|everything is there|all confirmed)", low):
        return {"action": "confirm_all"}
    if re.match(r"^(change|redo|new|reset)\s+(the\s+)?(menu|plan)\b", low):
        return {"action": "redo"}
    if low in ("help", "?", "menu help", "what can you do"):
        return {"action": "help"}

    # household profile: allergies, taste, how the cook should reach her
    m = re.search(r"\b([a-z\u0900-\u097F]+)\s+(?:is\s+|are\s+)?allergic\s+to\s+([a-z\u0900-\u097F ,&]+)", low)
    if m:
        from .profile import group_for
        words = [w for w in re.split(r"[ ,&]+|\band\b", m.group(2)) if w]
        groups = [g for g in (group_for(w) for w in words) if g]
        if groups:
            return {"action": "profile", "allergies": [(m.group(1), g) for g in dict.fromkeys(groups)]}
    style: dict = {}
    m = re.search(r"\bspice\s*(?:level)?\s*[:=]?\s*(mild|medium|hot)\b", low) or re.search(r"\b(mild|medium|hot)\s+spice\b", low)
    if m:
        style["spice"] = m.group(1)
    for key in ("oil", "salt", "sugar"):
        m = re.search(rf"\b(less|low|reduce|kam)\s+{key}\b", low)
        if m:
            style[key] = "low"
    if style:
        return {"action": "profile", "style": style}
    if re.search(r"\b(call|phone|ring)\s+(the\s+)?cook\b", low):
        return {"action": "profile", "cook_channel": "call"}
    if re.search(r"\b(message|whatsapp|text)\s+(the\s+)?cook\b", low) and not re.search(r"^(tell|ask)", low):
        return {"action": "profile", "cook_channel": "chat"}

    # per-day flags and household preferences
    flags: dict = {}
    m = re.search(r"\b(\d+)\s*(?:guests?|mehman|people extra|extra)\b", low) or re.search(r"\bguests?\s*[:=]?\s*(\d+)", low)
    if m:
        flags["guests"] = int(m.group(1))
    if re.search(r"\b(no|not|without)\s+(guests?|mehman)\b", low):
        flags["guests"] = 0
    if re.search(r"\b(fast|fasting|vrat|upvas|navratri|ekadashi)\b", low):
        flags["fasting"] = not re.search(r"\b(no|not|stop|end)\s+(fast|fasting|vrat)\b", low)
    if re.search(r"\b(cook|didi|bai|maid)\b.*\b(off|leave|not coming|chhutti|absent|nahi aa)", low) or \
            re.search(r"\bno cook\b", low):
        flags["cook_off"] = True
    if flags:
        return {"action": "flags", "flags": flags}
    prefs: dict = {}
    if re.search(r"\b(jain)\b", low):
        prefs["diet"] = "jain"
    elif re.search(r"\b(non[- ]?veg|nonveg|chicken ok|meat ok)\b", low):
        prefs["diet"] = "nonveg"
    elif re.search(r"\b(eggetarian|egg ok|eggs ok)\b", low):
        prefs["diet"] = "eggetarian"
    elif re.search(r"\b(pure veg|veg only|vegetarian|veg)\b", low) and not re.search(r"\bveg (pulao|sandwich|biryani)", low):
        prefs["diet"] = "vegetarian"
    if re.search(r"\b(no dairy|dairy[- ]free|lactose)\b", low):
        prefs["lactose_free"] = True
    if re.search(r"\bdairy ok\b", low):
        prefs["lactose_free"] = False
    m = re.search(r"\b(?:family|we are|we're|household)\s*(?:of|size|is)?\s*(\d+)\b", low)
    if m:
        prefs["family_size"] = int(m.group(1))
    m = re.search(r"\b(?:dislike|hate|don't like|dont like|no more)\s+([a-zऀ-ॿ ]+)", low)
    if m:
        its = find_items(tokens(m.group(1)))
        if its:
            prefs["dislike"] = its
    if prefs:
        return {"action": "prefs", "prefs": prefs}

    items = find_items(toks)
    have_words = {"have", "hai", "है", "there", "got", "bought", "left", "bacha", "bache", "बचा", "बचे", "stock"}
    zero_words = {"no", "nahi", "nahin", "khatam", "finished", "used", "out", "नहीं", "खत्म"}
    qty = find_number(toks)
    stock_like = items and (_has_unit(toks) or any(t in have_words for t in toks) or any(t in zero_words for t in toks)
                            or (qty is not None and len(toks) <= 3))
    dishes = _dishes_in(low)
    if dishes and not stock_like:
        return {"action": "dish_request", "dishes": dishes}
    if stock_like:
        updates = []
        for item in items:
            q, unit = find_unit(toks, item, qty)
            if any(t in zero_words for t in toks) and q is None:
                q = 0.0
            updates.append({"item": item, "qty": q, "unit": unit})
        return {"action": "stock", "updates": updates}

    nums = [int(n) for n in re.findall(r"\b([1-9])\b", low)]
    if nums and not any(t in NO for t in toks):
        return {"action": "choose", "choices": sorted(set(nums))}
    if any(t in YES for t in toks):
        return {"action": "yes"}
    if any(t in NO for t in toks):
        return {"action": "no", "text": text}
    return {"action": "other", "text": text}


# ---------- optional Claude parsing for the cook ----------
COOK_TYPES = ["used_up", "remaining", "low", "spoiled", "cannot_cook", "yes", "no", "leave", "done",
              "arrived", "ask_menu", "greeting", "unknown"]
COOK_TOOL = {
    "name": "report_intents",
    "description": "Structured intents from the cook's message (Hindi / Hinglish / English).",
    "input_schema": {
        "type": "object",
        "properties": {"intents": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": COOK_TYPES},
                "item": {"type": "string", "enum": sorted(ITEMS)},
                "qty": {"type": "number"},
                "unit": {"type": "string", "enum": ["g", "ml", "pcs"]},
                "reason": {"type": "string", "enum": ["stove", "cooker", "time", "other"]},
            },
            "required": ["type"]}}},
        "required": ["intents"],
    },
}


class ClaudeNLU:
    def __init__(self, api_key: str, model: str):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def cook(self, text: str, pending: dict | None) -> list[dict]:
        ctx = f"A confirmation is pending: {json.dumps(pending)}. " if pending else ""
        resp = self.client.messages.create(
            model=self.model, max_tokens=500, tools=[COOK_TOOL],
            tool_choice={"type": "tool", "name": "report_intents"},
            system=("You extract intents from a household cook's message about the kitchen. Only report what "
                    "was clearly said. Never infer that something is used up unless the cook said so. "
                    "'haan'/'sahi' => yes, 'nahi'/'galat' => no, only when answering a pending confirmation. "
                    "'aa gayi' => arrived; 'khana ban gaya' => done; 'kal nahi aaungi' => leave."),
            messages=[{"role": "user", "content": f"{ctx}Message: {text}"}])
        for block in resp.content:
            if block.type == "tool_use":
                return block.input.get("intents", [])
        return [{"type": "unknown"}]


class NLU:
    def __init__(self, claude: ClaudeNLU | None = None):
        self.claude = claude
        self.last_source = "rules"

    def cook(self, text: str, pending: dict | None = None) -> list[dict]:
        if self.claude:
            try:
                intents = self.claude.cook(text, pending)
                clean = [i for i in intents if i.get("type") in COOK_TYPES
                         and (i.get("item") in ITEMS or "item" not in i)]
                if clean:
                    self.last_source = "claude"
                    return clean
            except Exception:  # network / auth / schema problems must never break the kitchen
                pass
        self.last_source = "rules"
        return parse_cook(text, pending)

    def owner(self, text: str) -> dict:
        return parse_owner(text)
