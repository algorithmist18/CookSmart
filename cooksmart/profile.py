"""Household profile: who lives here, what they can't eat, how they like their food.

Stored in households.preferences (JSON). Two rules shape everything built on it:

* Allergies are HARD constraints. They filter menus in code and are repeated to the cook on every call;
  they are never left to a knowledge-base lookup that might miss.
* The cook sees INSTRUCTIONS, not diagnoses. "Diabetic" in the owner's profile becomes "less sugar, less
  rice" in anything the cook can read.
"""
from __future__ import annotations

from .recipes import ALLERGENS, ITEMS, RECIPES

AGE_GROUPS = {"child": "बच्चा", "adult": "बड़े", "elder": "बुज़ुर्ग"}
SPICE_HI = {"mild": "हल्का", "medium": "मध्यम", "hot": "तीखा"}
LEVEL_HI = {"low": "कम", "normal": "सामान्य", "high": "ज़्यादा"}

# Owner-stated health needs -> plain cooking instructions. This is household preference, not medical advice.
HEALTH_TO_INSTRUCTION = {
    "diabetes": "चीनी और मीठा बिलकुल कम; चावल, आलू और मैदा कम; दाल-सब्ज़ी ज़्यादा",
    "high_bp": "नमक कम; अचार, पापड़ और ऊपर से नमक नहीं",
    "cholesterol": "घी-तेल कम; तला हुआ नहीं; क्रीम नहीं",
    "weight_loss": "तेल कम; तला हुआ नहीं; सब्ज़ी और दाल ज़्यादा",
    "soft_food": "नरम, अच्छी तरह गला हुआ खाना; कम मसाला",
    "gas_acidity": "कम मसाला; ज़्यादा तला या भारी नहीं",
}


def members(prefs: dict) -> list[dict]:
    return [m for m in prefs.get("members", []) if m.get("name")]


def allergy_groups(prefs: dict) -> set[str]:
    out = {g for g in prefs.get("allergies", []) if g in ALLERGENS}
    for m in members(prefs):
        out |= {g for g in m.get("allergies", []) if g in ALLERGENS}
    return out


def allergy_items(prefs: dict) -> set[str]:
    return {i for g in allergy_groups(prefs) for i in ALLERGENS[g]["items"]}


def who_is_allergic(prefs: dict, group: str) -> list[str]:
    names = [m["name"] for m in members(prefs) if group in m.get("allergies", [])]
    return names or (["घर में कोई"] if group in prefs.get("allergies", []) else [])


def allergen_conflicts(recipe_ids: list[str], prefs: dict) -> list[dict]:
    """Which chosen dishes contain an allergen someone here reacts to (with the person and the ingredient)."""
    out = []
    for rid in recipe_ids:
        for item in RECIPES[rid]["needs"]:
            for g in allergy_groups(prefs):
                if item in ALLERGENS[g]["items"]:
                    out.append({"recipe": rid, "item": item, "group": g, "who": who_is_allergic(prefs, g)})
    return out


def group_for(word: str) -> str | None:
    w = word.lower().strip()
    for g, meta in ALLERGENS.items():
        if w == g or w in (a.lower() for a in meta["aliases"]):
            return g
    return None


def with_allergy(prefs: dict, name: str, group: str) -> dict:
    """Return new prefs with `group` added to member `name` (created if new)."""
    prefs = {**prefs, "members": [dict(m) for m in prefs.get("members", [])]}
    for m in prefs["members"]:
        if m["name"].lower() == name.lower():
            m["allergies"] = sorted({*m.get("allergies", []), group})
            return prefs
    prefs["members"].append({"name": name.title(), "age_group": "adult", "allergies": [group]})
    return prefs


def style_instructions(prefs: dict) -> list[str]:
    st = prefs.get("style", {})
    out = []
    if st.get("spice") in SPICE_HI:
        out.append(f"मसाला: {SPICE_HI[st['spice']]}")
    for key, label in (("oil", "तेल"), ("salt", "नमक"), ("sugar", "चीनी")):
        if st.get(key) in LEVEL_HI and st[key] != "normal":
            out.append(f"{label}: {LEVEL_HI[st[key]]}")
    return out


def member_instructions(m: dict) -> list[str]:
    """Everything the cook should do for one person, with no diagnosis in it."""
    out = []
    for g in m.get("allergies", []):
        out.append(f"{ALLERGENS[g]['hi']} बिलकुल नहीं (एलर्जी), न कम न ज़्यादा")
    for item in m.get("avoid", []):
        if item in ITEMS:
            out.append(f"{ITEMS[item]['hi']} नहीं देना")
    out += [HEALTH_TO_INSTRUCTION[h] for h in m.get("health", []) if h in HEALTH_TO_INSTRUCTION]
    if m.get("spice") in SPICE_HI:
        out.append(f"मसाला: {SPICE_HI[m['spice']]}")
    out += list(m.get("notes", []))
    # several rules can say the same thing ("कम मसाला"); say each clause once
    clauses = [c.strip() for line in out for c in line.split(";") if c.strip()]
    return list(dict.fromkeys(clauses))


def cook_safe_summary(prefs: dict) -> str:
    """One line per person, instructions only. Used in the KB and in call variables."""
    lines = []
    for m in members(prefs):
        ins = member_instructions(m)
        if ins:
            lines.append(f"{m['name']} ({AGE_GROUPS.get(m.get('age_group', 'adult'), 'बड़े')}): " + "; ".join(ins))
    return "\n".join(lines)


# ------------------------------------------------------------------ validated editing (Agent Studio)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DIETS = ("vegetarian", "eggetarian", "nonveg", "jain")


def _text(v, n: int) -> str:
    return "".join(c for c in str(v or "") if c.isprintable() or c in "\n").strip()[:n]


def sanitize_profile(data: dict) -> tuple[dict, list[str]]:
    """Validate what the profile editor sends. Returns (clean, errors); clean only has keys that were provided."""
    errors: list[str] = []
    out: dict = {}

    if "family_size" in data:
        try:
            n = int(data["family_size"])
            (out.__setitem__("family_size", n) if 1 <= n <= 20 else errors.append("Family size must be 1–20."))
        except (TypeError, ValueError):
            errors.append("Family size must be a number.")
    if "diet" in data:
        (out.__setitem__("diet", data["diet"]) if data["diet"] in DIETS else errors.append("Unknown diet."))
    if "lactose_free" in data:
        out["lactose_free"] = bool(data["lactose_free"])
    if "cook_name" in data:
        out["cook_name"] = _text(data["cook_name"], 40) or "दीदी"
    if "cook_phone" in data:
        phone = _text(data["cook_phone"], 20)
        import re
        if phone and not re.fullmatch(r"\+?[0-9][0-9 \-]{6,18}", phone):
            errors.append("The cook's phone number doesn't look right.")
        else:
            out["cook_phone"] = phone or None

    if "members" in data:
        members_out = []
        if not isinstance(data["members"], list) or len(data["members"]) > 12:
            errors.append("At most 12 household members.")
        else:
            for i, m in enumerate(data["members"], 1):
                name = _text(m.get("name"), 40)
                if not name:
                    errors.append(f"Member {i} needs a name.")
                    continue
                if m.get("age_group", "adult") not in AGE_GROUPS:
                    errors.append(f"{name}: unknown age group.")
                    continue
                bad = [a for a in m.get("allergies", []) if a not in ALLERGENS]
                bad += [h for h in m.get("health", []) if h not in HEALTH_TO_INSTRUCTION]
                bad += [x for x in m.get("avoid", []) if x not in ITEMS]
                if bad:
                    errors.append(f"{name}: unknown value(s) {bad}.")
                    continue
                if m.get("spice") and m["spice"] not in SPICE_HI:
                    errors.append(f"{name}: unknown spice level.")
                    continue
                members_out.append({
                    "name": name, "age_group": m.get("age_group", "adult"),
                    "allergies": sorted(set(m.get("allergies", []))), "health": sorted(set(m.get("health", []))),
                    "avoid": sorted(set(m.get("avoid", []))), **({"spice": m["spice"]} if m.get("spice") else {}),
                    "notes": [t for t in (_text(n, 200) for n in m.get("notes", [])[:5]) if t]})
            out["members"] = members_out

    if "style" in data:
        st = {}
        for k, allowed in (("spice", SPICE_HI), ("oil", LEVEL_HI), ("salt", LEVEL_HI), ("sugar", LEVEL_HI)):
            v = (data["style"] or {}).get(k)
            if v:
                (st.__setitem__(k, v) if v in allowed else errors.append(f"Unknown {k} setting."))
        out["style"] = st

    if "customs" in data:
        customs = []
        for c in (data["customs"] or [])[:10]:
            if isinstance(c, str):
                if _text(c, 200):
                    customs.append(_text(c, 200))
            elif isinstance(c, dict):
                wd = (c.get("weekday") or "").lower()
                avoid = [x for x in c.get("avoid", []) if x in ITEMS]
                if wd and wd not in WEEKDAYS:
                    errors.append("A custom has an unknown weekday.")
                    continue
                customs.append({"weekday": wd, "avoid": avoid, "text": _text(c.get("text"), 200)})
        out["customs"] = customs

    if "kitchen" in data:
        k = data["kitchen"] or {}
        try:
            out["kitchen"] = {"burners": max(0, min(10, int(k.get("burners") or 0))),
                              "cooker_litres": max(0, min(20, float(k.get("cooker_litres") or 0))),
                              "notes": [t for t in (_text(n, 200) for n in (k.get("notes") or [])[:8]) if t]}
        except (TypeError, ValueError):
            errors.append("Kitchen numbers must be numbers.")
    if "units" in data:
        try:
            ml = int((data["units"] or {}).get("katori_ml") or 150)
            (out.__setitem__("units", {"katori_ml": ml}) if 50 <= ml <= 400 else errors.append("A katori is 50–400 ml."))
        except (TypeError, ValueError):
            errors.append("Katori size must be a number.")
    return out, errors
