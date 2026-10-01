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


def norm(text: str) -> str:
    t = text.lower().translate(_DEV_DIGITS)
    return t.replace("़", "").replace("ँ", "ं")  # drop nukta, chandrabindu -> anusvara


def tokens(text: str) -> list[str]:
    return [t.strip(".") for t in TOKEN_RE.findall(norm(text)) if t.strip(".")]


ITEM_BY_ALIAS = {norm(a): item for item, al in ALIASES.items() for a in al}
DISH_ALIASES = {}
for _rid, _r in RECIPES.items():
    DISH_ALIASES[norm(_r["name"])] = _rid
    DISH_ALIASES[norm(_r["hi"])] = _rid
    DISH_ALIASES[_rid.replace("_", " ")] = _rid

YES = {"haan", "han", "ha", "haa", "ji", "sahi", "yes", "y", "ok", "okay", "theek", "thik", "correct",
       "yep", "yeah", "approve", "approved", "हां", "हा", "जी", "सही", "ठीक"}
NO = {"nahi", "nahin", "nhi", "no", "galat", "na", "nope", "नहीं", "नही", "गलत", "decline"}
USED_UP = {"khatam", "khtm", "khatm", "finished", "over", "empty", "खत्म", "खतम", "समाप्त"}
REMAINING = {"bache", "bacha", "bachi", "bachey", "left", "remaining", "बचे", "बचा", "बची"}
LOW = {"kam", "low", "कम"}
BAD = {"kharab", "band", "broken", "खराब", "बंद"}
STOVE = {"gas", "stove", "chulha", "चूल्हा", "गैस"}
TIME = {"time", "samay", "टाइम", "समय"}
NEG = {"nahi", "nahin", "nhi", "kam", "less", "नहीं", "नही", "कम"}
CONJ = {"aur", "and", "और", "phir", "फिर"}
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
def parse_cook(text: str, pending: dict | None = None) -> list[dict]:
    """-> list of intents: used_up | remaining | low | cannot_cook | yes | no | unknown."""
    toks = tokens(text)
    if pending and 0 < len(toks) <= 4:
        if any(t in YES for t in toks):
            return [{"type": "yes"}]
        if any(t in NO for t in toks):
            return [{"type": "no"}]
    intents: list[dict] = []
    for cl in _clauses(text):
        # equipment / time problems
        if any(t in STOVE for t in cl) and any(t in BAD or t in NEG for t in cl):
            intents.append({"type": "cannot_cook", "reason": "stove"})
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
            elif (any(t in USED_UP for t in cl) or _has_seq(cl, NO, {"hai", "h", "है"})
                  or ({"poora", "पूरा", "pura"} & set(cl) and {"lag", "लग", "use", "gaya"} & set(cl))):
                intents.append({"type": "used_up", "item": item})
            elif any(t in LOW for t in cl):
                intents.append({"type": "low", "item": item})
    return intents or [{"type": "unknown"}]


# ---------- owner ----------
def parse_owner(text: str) -> dict:
    """-> {action: ...}. Interpretation of yes/no/choose depends on the plan state (done by the agent)."""
    toks = tokens(text)
    low = norm(text).strip()
    m = re.match(r"^mode\s+(auto|approve)\b", low)
    if m:
        return {"action": "mode", "mode": m.group(1)}
    m = re.match(r"^cap\s+(\d+)", low)
    if m:
        return {"action": "cap", "cap": int(m.group(1))}
    if re.match(r"^(all good|sab theek|sab sahi|everything is there|all confirmed)", low):
        return {"action": "confirm_all"}

    for alias, rid in sorted(DISH_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in low:
            return {"action": "dish_request", "dish": rid}

    items = find_items(toks)
    if items:
        have_words = {"have", "hai", "है", "there", "got", "bought", "left", "bacha", "bache", "बचा", "बचे", "stock"}
        zero_words = {"no", "nahi", "nahin", "khatam", "finished", "used", "out", "नहीं", "खत्म"}
        qty = find_number(toks)
        if qty is not None or any(t in have_words for t in toks) or any(t in zero_words for t in toks):
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
COOK_TOOL = {
    "name": "report_intents",
    "description": "Structured intents from the cook's message (Hindi / Hinglish / English).",
    "input_schema": {
        "type": "object",
        "properties": {"intents": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["used_up", "remaining", "low", "cannot_cook",
                                                    "yes", "no", "unknown"]},
                "item": {"type": "string", "enum": sorted(ITEMS)},
                "qty": {"type": "number"},
                "unit": {"type": "string", "enum": ["g", "ml", "pcs"]},
                "reason": {"type": "string", "enum": ["stove", "time", "other"]},
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
                    "'haan'/'sahi' => yes, 'nahi'/'galat' => no, only when answering a pending confirmation."),
            messages=[{"role": "user", "content": f"{ctx}Message: {text}"}])
        for block in resp.content:
            if block.type == "tool_use":
                return [i for i in block.input.get("intents", []) if i.get("type") != "unknown" or True]
        return [{"type": "unknown"}]


class NLU:
    def __init__(self, claude: ClaudeNLU | None = None):
        self.claude = claude
        self.last_source = "rules"

    def cook(self, text: str, pending: dict | None = None) -> list[dict]:
        if self.claude:
            try:
                intents = self.claude.cook(text, pending)
                clean = [i for i in intents if i.get("type") in
                         {"used_up", "remaining", "low", "cannot_cook", "yes", "no", "unknown"}
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
