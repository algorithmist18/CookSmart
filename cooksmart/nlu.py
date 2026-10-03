"""Language understanding for both chats.

Rule-based parsers (Hindi in Devanagari, romanised Hinglish, English) are the always-available base.
When ANTHROPIC_API_KEY is set, Claude parses the cook's messages first and the rules are the fallback.
Either way the result is the same small structured vocabulary, validated against the item catalog.
"""
from __future__ import annotations

import difflib
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
DISH_ALIASES.update({"chicken curry": "chicken_curry", "rajma chawal": "rajma_chawal", "chole": "chole",
                     "khichdi": "moong_khichdi", "khichri": "moong_khichdi", "pulao": "veg_pulao", "paratha": "aloo_paratha",
                     "sandwich": "veg_sandwich", "omelette": "bread_omelette", "omelet": "bread_omelette", "chilla": "besan_chilla",
                     "cheela": "besan_chilla", "dal fry": "dal_tadka", "daal": "dal_tadka"})
# everyday two-dish orders
COMBOS = {"dal chawal": ["dal_tadka", "jeera_rice"], "dal rice": ["dal_tadka", "jeera_rice"], "daal chawal": ["dal_tadka", "jeera_rice"],
          "dal roti": ["dal_tadka", "roti"], "daal roti": ["dal_tadka", "roti"], "roti sabzi": ["aloo_gobi", "roti"],
          "sabzi roti": ["aloo_gobi", "roti"]}

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
    """Every dish named in the text, in order of appearance (longest names win, no overlaps). What is left over is
    matched loosely, so a misspelt name ('pallak panner') still finds its dish."""
    found, text = [], low
    for phrase, rids in COMBOS.items():
        for m in re.finditer(WORD.format(re.escape(phrase)), text):
            found += [(m.start(), r) for r in rids]
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    for alias, rid in sorted(DISH_ALIASES.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(WORD.format(re.escape(alias)), text):
            found.append((m.start(), rid))
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    found += _fuzzy_dishes(text)
    out: list[str] = []
    for _, rid in sorted(found):
        if rid not in out:
            out.append(rid)
    return out


def _fuzzy_dishes(residual: str) -> list[tuple[int, str]]:
    """Typos and spelling variants in the part of the message no dish name matched. Only longer names are matched
    this way (short ones like 'roti' would collide with ordinary words)."""
    names = [a for a in DISH_ALIASES if a.isascii() and len(a) >= 6]
    words = [(m.start(), m.group()) for m in re.finditer(r"[a-z]+", residual)]
    out: list[tuple[int, str]] = []
    for size in (3, 2, 1):
        for i in range(len(words) - size + 1):
            gram = " ".join(w for _, w in words[i:i + size])
            if len(gram) < 6 or any(words[i][0] == pos for pos, _ in out):
                continue
            hit = difflib.get_close_matches(gram, names, n=1, cutoff=0.84)
            if hit:
                out.append((words[i][0], DISH_ALIASES[hit[0]]))
    return out


ORDINALS = {"first": 1, "1st": 1, "pehla": 1, "pehli": 1, "pahla": 1, "second": 2, "2nd": 2, "doosra": 2, "dusra": 2,
            "doosri": 2, "third": 3, "3rd": 3, "teesra": 3, "teesri": 3, "पहला": 1, "दूसरा": 2, "तीसरा": 3, "पहली": 1}
QUESTION_WORDS = {"what", "why", "how", "which", "when", "where", "who", "kya", "kaun", "kitna", "kitne", "kab", "kyun", "kyon",
                  "kahan", "kaise", "is", "are", "do", "does", "can", "will", "should", "could", "क्या", "कब", "क्यों", "कितना", "कितने"}


REQUEST_RE = re.compile(r"^(?:can|could|will|would)\s+(?:you|we|i|u)\s+(?:please\s+)?(?:make|show|give|change|plan|do|add|order|cook|get|try|pick|suggest|find)\b|^(?:please|pls)\b")


def is_question(text: str) -> bool:
    low = norm(text).strip()
    toks = tokens(text)
    if REQUEST_RE.match(low):                       # "can you make it quicker?" is a request, not a question
        return False
    return len(toks) >= 3 and ("?" in text or toks[0] in QUESTION_WORDS)


MEAL_KW = {"breakfast": r"breakfast|nashta|naashta|nasta|naashte|nashte|subah ka khana|in the morning|subah",
           "lunch": r"lunch|dopahar ka khana|dopahar|in the afternoon",
           "dinner": r"dinner|raat ka khana|raat ko|raat me|raat mein|at night|tonight|in the evening"}
_ALL_KW = "|".join(MEAL_KW.values())
_CONNECT = re.compile(r"(?:\bfor|\bke liye|\bka|\bke|\bmein|\bme|\bko|\bat|\bin|\bki)\s*$")
_NEGATION = re.compile(r"\b(no|nothing|nope|skip|without|not needed|nahi|nahin|mat|chhod|chod|don'?t)\b")


def _meal_request(low: str) -> dict | None:
    """'poha for breakfast and dal rice for lunch', 'breakfast poha, lunch dal rice', 'dinner mein khichdi',
    'nothing for lunch' -> which dishes for which meal (or which meal to skip)."""
    hits = [(m.start(), m.end(), meal) for meal, pat in MEAL_KW.items() for m in re.finditer(rf"\b(?:{pat})\b", low)]
    if not hits:
        return None
    hits.sort()
    named: dict[str, list[str]] = {}
    skip: list[str] = []
    for i, (s, e, meal) in enumerate(hits):
        prev_end = hits[i - 1][1] if i else 0
        next_start = hits[i + 1][0] if i + 1 < len(hits) else len(low)
        before, after = low[prev_end:s], low[e:next_start]
        if re.match(r"in the|at night|tonight", low[s:e]) and _dishes_in(before):
            dishes = _dishes_in(before)                      # "<dish> in the morning"
        elif _CONNECT.search(before.rstrip() + " ") and _dishes_in(_CONNECT.sub(" ", before.rstrip() + " ")):
            dishes = _dishes_in(before)                      # "<dish> for <meal>"
        else:
            dishes = _dishes_in(after)                       # "<meal> <dish>"
        if dishes:
            named.setdefault(meal, [])
            named[meal] += [d for d in dishes if d not in named[meal]]
        elif _NEGATION.search(low[max(0, s - 18):s]) or _NEGATION.search(after[:22]):
            skip.append(meal)
    if named:
        return {"action": "meal_request", **{m: named.get(m, []) for m in MEAL_KW}}
    if skip:
        return {"action": "skip", "meal": skip[0]}
    return None


YES_PHRASES = re.compile(r"\b(go ahead|sounds good|looks good|book it|place (?:the |it |my )?order|order it|do it|that works|perfect|great|fine|sure|"
                         r"all right|alright|karo|kar do|kardo|theek hai|thik hai|chalega|done)\b")
NO_PHRASES = re.compile(r"\b(don'?t (?:order|buy|place|book)|do not (?:order|buy|place)|hold it|cancel|not now|no thanks|leave it|forget it|"
                        r"mat (?:karo|lo|mangao)|nahi chahiye|rehne do|reh ne do)\b")
CHAT = {
    "thanks": re.compile(r"^(?:thanks|thank you|thankyou|thx|ty|shukriya|dhanyavad|dhanyawad|धन्यवाद|शुक्रिया)\b"),
    "hello": re.compile(r"^(?:hi|hii+|hello|hey|namaste|namaskar|good (?:morning|afternoon|evening)|नमस्ते)\b"),
    "night": re.compile(r"^(?:good ?night|gn|shubh ratri|शुभ रात्रि)\b"),
    "pause": re.compile(r"^(?:hold on|wait|one sec(?:ond)?|just a (?:sec|minute|moment)|ek minute|ruko|ek sec)\b"),
    "bye": re.compile(r"^(?:bye|see you|ttyl|tata)\b"),
}


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
    if re.match(r"^(?:skip|chhod do|chod do)\b", low):
        mk = _meal_request(low)
        return {"action": "skip", **({"meal": mk["meal"]} if mk and mk.get("action") == "skip" else {})} if not (mk and mk["action"] == "meal_request") else mk
    for kind, pat in CHAT.items():
        if pat.search(low) and len(toks) <= 5:
            return {"action": "chat", "kind": kind}
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
    if re.search(r"\b(fill|stock|restock|refill|replenish|load)\w*\s+(up\s+)?(the\s+|my\s+)?(fridge|kitchen|pantry)\b|\brestock\b|fridge\s+bhar|stock\s+up\b", low):
        return {"action": "restock"}
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
    if not m and re.search(r"\b(guests?|mehman)\b", low) and not re.search(r"\b(no|not|without)\s+(guests?|mehman)\b", low):
        n = re.search(r"\b(\d+)\b", low)                      # "we have guests tomorrow, 5 people"
        if n:
            flags["guests"] = int(n.group(1))
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

    mr = _meal_request(low)
    if mr:
        return mr

    items = find_items(toks)
    have_words = {"have", "hai", "है", "there", "got", "bought", "left", "bacha", "bache", "बचा", "बचे", "stock"}
    zero_words = {"no", "nahi", "nahin", "khatam", "finished", "used", "out", "नहीं", "खत्म", "over", "bad", "rotten", "spoiled",
                  "spoilt", "kharab", "sad", "sada", "expired", "gone", "ran"}
    qty = find_number(toks)
    stock_like = items and (_has_unit(toks) or any(t in have_words for t in toks) or any(t in zero_words for t in toks)
                            or (qty is not None and len(toks) <= 3))
    dishes = _dishes_in(low)
    wants = re.search(r"\b(can|could|may|shall|let'?s|want|wanna|make|cook|bana\w*|chahiye|please|i'?d like|would like|prefer|"
                      r"i'?ll (?:have|take|go for|go with|eat)|give me|let me have|we'?ll have|i'?ll)\b", low)
    evidence = (set(have_words) | zero_words | {"left", "bacha", "bache", "stock", "bought", "aaya", "aayi"}) - {"no", "nahi", "nahin", "नहीं"}
    if (items and not dishes and len(toks) >= 3 and re.search(r"\b(no|without|bina|avoid|not|don'?t want|nahi chahiye|mat)\b", low)
            and not (evidence & set(toks)) and qty is None and not _has_unit(toks)
            and re.search(r"\b(in|please|today|tomorrow|this|that|for|dinner|lunch|breakfast|dish|meal|it|wala|mein|me)\b", low)):
        return {"action": "other", "text": text}          # "no onion in it": a wish about the dish, not a stock report
    if dishes and (not stock_like or wants):          # "can I have palak paneer?" asks for a dish, it doesn't report stock
        return {"action": "dish_request", "dishes": dishes}
    if stock_like and is_question(text):               # "do we have paneer?" asks, it doesn't report
        return {"action": "ask", "text": text}
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
    if is_question(text):
        return {"action": "ask", "text": text}
    ords = [ORDINALS[t] for t in toks if t in ORDINALS]
    if ords and len(toks) <= 6 and not items:                       # "the second one", "doosra wala", "option three"
        return {"action": "choose", "choices": sorted(set(ords))}
    if len(toks) <= 7 and NO_PHRASES.search(low):
        return {"action": "no", "text": text}
    if len(toks) <= 7 and YES_PHRASES.search(low):
        return {"action": "yes"}
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

    def owner(self, text: str, ctx: dict) -> dict:
        resp = self.client.messages.create(
            model=self.model, max_tokens=500, tools=[OWNER_TOOL], system=OWNER_SYSTEM,
            tool_choice={"type": "tool", "name": "interpret"},
            messages=[{"role": "user", "content": f"Assistant state:\n{_ctx_text(ctx)}\n\nOwner's message: {text}"}])
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        return {"action": "other"}

    def answer(self, question: str, facts: str) -> str | None:
        resp = self.client.messages.create(
            model=self.model, max_tokens=350,
            system=("You are the assistant on a family's smart fridge. Answer the owner's question using ONLY the FACTS. "
                    "Be brief (at most 4 short lines), plain and friendly. If the facts don't say, say you don't know. "
                    "Never mention prices to anyone but the owner, and never invent stock."),
            messages=[{"role": "user", "content": f"FACTS:\n{facts}\n\nQuestion: {question}"}])
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        return text or None


def _ctx_text(ctx: dict) -> str:
    lines = [f"state: {ctx.get('state', 'none')}", f"asking about: {ctx.get('stage') or 'nothing right now'}"]
    for o in ctx.get("options", []):
        lines.append(f"option {o['n']}: {o['label']}, dishes: {', '.join(o['dishes'])}" + (f" (to buy: {', '.join(o['buy'])})" if o.get("buy") else ""))
    if ctx.get("meals"):
        lines.append("already chosen: " + "; ".join(f"{m}: {', '.join(v) or 'skipped'}" for m, v in ctx["meals"].items()))
    if ctx.get("order"):
        lines.append(f"order waiting for approval: {ctx['order']}")
    return "\n".join(lines)


OWNER_ACTIONS = ["choose", "yes", "no", "skip", "dish_request", "meal_request", "stock", "flags", "mode", "cap", "relay",
                 "redo", "help", "confirm_all", "restock", "ask", "other"]
OWNER_TOOL = {
    "name": "interpret",
    "description": "What the household owner means by their message to the kitchen assistant.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": OWNER_ACTIONS},
            "choices": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 9},
                        "description": "Option numbers picked, resolving 'the second one', 'the lighter one', 'both' using the numbered options"},
            "dishes": {"type": "array", "items": {"type": "string", "enum": sorted(RECIPES)}},
            "breakfast": {"type": "array", "items": {"type": "string", "enum": sorted(RECIPES)}},
            "lunch": {"type": "array", "items": {"type": "string", "enum": sorted(RECIPES)}},
            "dinner": {"type": "array", "items": {"type": "string", "enum": sorted(RECIPES)}},
            "updates": {"type": "array", "items": {"type": "object", "properties": {
                "item": {"type": "string", "enum": sorted(ITEMS)}, "qty": {"type": "number"},
                "unit": {"type": "string", "enum": ["g", "ml", "pcs"]}}, "required": ["item"]}},
            "flags": {"type": "object", "properties": {"guests": {"type": "integer"}, "fasting": {"type": "boolean"},
                                                       "cook_off": {"type": "boolean"}}},
            "mode": {"type": "string", "enum": ["auto", "approve"]},
            "cap": {"type": "integer"},
            "text": {"type": "string", "description": "For relay: the message for the cook. For other/no: the owner's wish in a few "
                     "words (e.g. 'something lighter', 'no onion', 'quicker'), which re-plans the current meal."},
        },
        "required": ["action"],
    },
}
OWNER_SYSTEM = """You are the language understanding of a household kitchen assistant that lives on the family's smart fridge.
The owner writes in English, Hindi, Hinglish or a mix, with typos and loose phrasing. Decide what they mean.
You are given the assistant's current state: which meal it is asking about, the numbered options just shown, what is
already chosen, and any order waiting for approval. Use it:
- "the second one", "that one", "both", "the paneer one", "lighter one" -> choose, with the option numbers.
- naming a dish (even misspelt) -> dish_request (or meal_request if they name breakfast/lunch/dinner dishes separately).
- "no onion", "something quicker", "spicier please", "not paneer again" -> other, with text = the wish.
- "I have 2 tomatoes", "paneer is finished", "bought milk 1 litre" -> stock.
- a question about the kitchen ("what's expiring?", "why option 2?", "do we have curd?") -> ask, text = the question.
- "fill the fridge", "restock" -> restock. "skip breakfast", "nothing for lunch" -> skip.
- "yes/ok/go ahead" / "no/hold" mean approval or refusal of the pending order when one is waiting, else accepting
  or refusing the options shown.
Never invent dishes or items; only use the allowed values. When unsure, answer other."""


def _is_plain_command(text: str, parsed: dict) -> bool:
    """Exact, unambiguous inputs the rules already get right: no need to spend a model call."""
    low = norm(text).strip()
    a = parsed["action"]
    if a in ("mode", "cap", "relay", "help", "confirm_all", "redo", "skip", "restock"):
        return True
    if a == "choose":
        return bool(re.fullmatch(r"[\s\d,&+]*(?:and|aur|और)?[\s\d,&+]*", low))
    if a in ("yes", "no"):
        return len(tokens(text)) <= 2
    return False


def _validate_owner(raw: dict | None) -> dict | None:
    """Turn the model's answer into the same dict parse_owner returns, or None if any of it is out of vocabulary."""
    if not raw or raw.get("action") not in OWNER_ACTIONS:
        return None
    a = raw["action"]
    dishes = lambda k: [d for d in raw.get(k, []) if d in RECIPES]          # noqa: E731
    if a == "choose":
        ch = sorted({int(c) for c in raw.get("choices", []) if 1 <= int(c) <= 9})
        return {"action": "choose", "choices": ch} if ch else None
    if a == "dish_request":
        return {"action": "dish_request", "dishes": dishes("dishes")} if dishes("dishes") else None
    if a == "meal_request":
        out = {m: dishes(m) for m in ("breakfast", "lunch", "dinner")}
        return {"action": "meal_request", **out} if any(out.values()) else None
    if a == "stock":
        ups = []
        for u in raw.get("updates", []):
            if u.get("item") in ITEMS:
                ups.append({"item": u["item"], "qty": float(u["qty"]) if u.get("qty") is not None else None,
                            "unit": u.get("unit") or ITEMS[u["item"]]["unit"]})
        return {"action": "stock", "updates": ups} if ups else None
    if a == "flags":
        fl = {k: v for k, v in (raw.get("flags") or {}).items() if k in ("guests", "fasting", "cook_off")}
        return {"action": "flags", "flags": fl} if fl else None
    if a == "mode":
        return {"action": "mode", "mode": raw["mode"]} if raw.get("mode") in ("auto", "approve") else None
    if a == "cap":
        return {"action": "cap", "cap": int(raw["cap"])} if raw.get("cap") is not None else None
    if a == "relay":
        return {"action": "relay", "text": raw["text"]} if raw.get("text") else None
    if a in ("ask",):
        return {"action": "ask", "text": raw.get("text") or ""}
    if a in ("no", "other"):
        return {"action": a, "text": raw.get("text") or ""}
    return {"action": a}


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

    def owner(self, text: str, ctx: dict | None = None) -> dict:
        """Rules answer the plain commands instantly; anything looser goes to Claude (with the chat's state), and
        the rules are the fallback if there is no key, no network or an unusable answer."""
        base = parse_owner(text)
        self.last_source = "rules"
        if not self.claude or _is_plain_command(text, base):
            return base
        try:
            got = _validate_owner(self.claude.owner(text, ctx or {}))
        except Exception:                      # never let a language-model hiccup break the kitchen
            return base
        if got and got["action"] != "other":
            self.last_source = "claude"
            return got
        return base if base["action"] != "other" else (got or base)

    def answer(self, question: str, facts: str) -> str | None:
        """A grounded reply to a question about the kitchen, or None (the agent then answers from the rules)."""
        if not self.claude:
            return None
        try:
            return self.claude.answer(question, facts)
        except Exception:
            return None
