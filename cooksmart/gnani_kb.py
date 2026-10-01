"""Generates the Gnani agent's knowledge base (markdown documents) and FAQs from the household profile.

What goes here: things that change rarely and need explaining, namely this family's people, taste and customs,
ingredient care and ageing, health notes, kitchen setup, emergencies, boundaries and units.

What does NOT go here: today's stock, use-by dates, who is eating today, today's cautions. Those change daily and
a knowledge base is uploaded documents, so they travel as call variables (see cookbrief.py). Allergies are in BOTH:
here for the "why and how", and in the prompt on every call because retrieval can miss.

Privacy: the cook only gets instructions ("less sugar"), never diagnoses. Uploading these files shares them with
Gnani, so only include what the household is comfortable sharing.
"""
from __future__ import annotations

import json

from . import knowledge as kn
from . import profile as prof
from .recipes import ALLERGENS, ITEMS, RECIPES

DEMO_PROFILE = {
    "cook_name": "सुनीता दीदी", "diet": "vegetarian",
    "members": [
        {"name": "आरव", "age_group": "child", "allergies": ["peanut"], "spice": "mild",
         "notes": ["टिफ़िन में सब्ज़ी सूखी रखें", "प्याज़ बारीक कटी हो, दिखे नहीं"]},
        {"name": "दादी", "age_group": "elder", "health": ["soft_food", "gas_acidity"], "notes": ["रात का खाना हल्का रखें"]},
        {"name": "पापा", "age_group": "adult", "health": ["high_bp", "diabetes"]},
        {"name": "मम्मी", "age_group": "adult", "spice": "medium"},
    ],
    "style": {"spice": "medium", "oil": "low", "salt": "normal", "sugar": "low"},
    "customs": [{"weekday": "tuesday", "avoid": ["onion"], "text": "मंगलवार को प्याज़-लहसुन नहीं"}],
    "signature": {"palak_paneer": "क्रीम कम रखें, पनीर के टुकड़े बड़े", "dal_tadka": "घी का तड़का, जीरा थोड़ा ज़्यादा"},
    "likes": ["paneer", "rajma"], "dislikes": [],
    "meal_times": {"नाश्ता": "8:00", "दोपहर": "1:00 (आरव का टिफ़िन 7:30 तक तैयार)", "रात": "8:30"},
    "kitchen": {"burners": 2, "cooker_litres": 3,
                "notes": ["मसाले ऊपर वाली अलमारी में", "आटा नीले डिब्बे में", "फ्रिज के नीचे वाले खाने में सब्ज़ियाँ"]},
    "units": {"katori_ml": 150},
}


def _md(title: str, *sections: tuple[str, list[str] | str]) -> str:
    out = [f"# {title}", ""]
    for head, body in sections:
        out += [f"## {head}", ""]
        out += [body] if isinstance(body, str) else [f"- {b}" if not b.startswith(("-", "|", "#")) else b for b in body]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _name(item: str) -> str:
    return ITEMS[item]["hi"]


def doc_household(prefs: dict, family: int) -> str:
    people = [f"{m['name']} ({prof.AGE_GROUPS.get(m.get('age_group', 'adult'), 'एडल्ट')})" for m in prof.members(prefs)]
    ins = [f"{m['name']}: " + "; ".join(prof.member_instructions(m)) for m in prof.members(prefs)
           if prof.member_instructions(m)]
    times = [f"{k}: {v}" for k, v in prefs.get("meal_times", {}).items()]
    customs = [c if isinstance(c, str) else c.get("text", "") for c in prefs.get("customs", [])]
    return _md(
        "हाउसहोल्ड प्रोफ़ाइल",
        ("कौन खाता है", [f"रोज़ लगभग {family} लोग खाना खाते हैं. गेस्ट हों तो हर कॉल में बताया जाएगा कि आज कितने लोग हैं."]
         + (["घर के लोग: " + ", ".join(people)] if people else [])),
        ("हर मेंबर के लिए इंस्ट्रक्शन", ins or ["कोई स्पेशल इंस्ट्रक्शन नहीं"]),
        ("मील का टाइम", times or ["फ़िक्स नहीं"]),
        ("घर के रूल्स और कस्टम्स", [c for c in customs if c] or ["कोई स्पेशल रूल नहीं"]),
        ("ज़रूरी", "यहाँ सिर्फ़ इंस्ट्रक्शन हैं. किसी की बीमारी या पर्सनल बात डिस्कस न करें. ज़्यादा जानना हो तो मैडम/सर से पूछने को कहें."),
    )


def doc_allergy(prefs: dict) -> str:
    groups = sorted(prof.allergy_groups(prefs))
    per = []
    for g in groups:
        who = ", ".join(prof.who_is_allergic(prefs, g))
        per.append(f"**{ALLERGENS[g]['hi']}** — {who}. बिलकुल नहीं: न कम, न ज़्यादा, न तड़के में, न सजावट में, न चटनी में.")
    hidden = [
        "बेसन = चना; छोले = चना",
        "ब्रेड में गेहूं होता है, और अक्सर मिल्क या एग भी",
        "पनीर, दही, क्रीम, बटर, घी — सब मिल्क से बनते हैं",
        "पैकेट वाले मसाले, नमकीन, चटनी, सॉस में पीनट या मिल्क के ट्रेस हो सकते हैं — लेबल पढ़ें, पक्का न हो तो यूज़ न करें",
        "पोहा, उपमा और चाट में पीनट अक्सर ऊपर से डाले जाते हैं — एलर्जी वाले के हिस्से में बिलकुल नहीं",
    ]
    return _md(
        "एलर्जी और सेफ़्टी (सबसे ज़रूरी डॉक्युमेंट)",
        ("प्रायोरिटी", "हर कॉल की शुरुआत में बताए गए 'कॉशन' इस डॉक्युमेंट से भी ऊपर हैं. शक हो तो चीज़ यूज़ न करें और मैडम/सर से पूछें."),
        ("किसको किससे एलर्जी है", per or ["अभी किसी की एलर्जी रजिस्टर्ड नहीं है"]),
        ("हिडन सोर्स", hidden),
        ("बचाव के तरीके", ["एलर्जी वाले का खाना पहले और अलग बर्तन में बनाएँ", "अलग स्पून/कड़छी; यूज़ से पहले साफ़ धोएँ",
                           "गेस्ट के लिए भी वही रूल"]),
        ("अगर एलर्जी रिएक्शन लगे (होंठ/चेहरा सूजना, साँस में दिक्कत, रैश, उल्टी)",
         ["तुरंत खिलाना बंद करें", "तुरंत मैडम/सर को कॉल करें और 112 पर कॉल करें; साँस की प्रॉब्लम में देर न करें",
          "पेशेंट को अकेला न छोड़ें", "यह डॉक्टर की एडवाइस की जगह नहीं है"]),
    )


def doc_taste(prefs: dict) -> str:
    st = prof.style_instructions(prefs)
    sig = [f"{RECIPES[r]['hi']}: {t}" for r, t in prefs.get("signature", {}).items() if r in RECIPES]
    likes = [_name(i) for i in prefs.get("likes", []) if i in ITEMS]
    dislikes = [_name(i) for i in prefs.get("dislikes", []) if i in ITEMS]
    persons = [f"{m['name']}: " + "; ".join(x for x in prof.member_instructions(m) if "एलर्जी" not in x)
               for m in prof.members(prefs) if any("एलर्जी" not in x for x in prof.member_instructions(m))]
    return _md(
        "इस घर का टेस्ट और पर्सनलाइज़ेशन",
        ("घर की जनरल पसंद", st or ["सामान्य"]),
        ("हर मेंबर की पसंद", persons or ["कोई स्पेशल नहीं"]),
        ("इस घर के स्पेशल तरीके", sig or ["कोई स्पेशल नहीं"]),
        ("फ़ेवरेट आइटम्स", [", ".join(likes)] if likes else ["रजिस्टर्ड नहीं"]),
        ("जो पसंद नहीं", [", ".join(dislikes)] if dislikes else ["रजिस्टर्ड नहीं"]),
        ("नोट", "अगर घर की पसंद और किसी टिप में फ़र्क हो, तो घर की पसंद फ़ॉलो करें."),
    )


def doc_care() -> str:
    lines: list[str] = []
    for item, c in kn.ITEM_CARE.items():
        if not c["lasts"] or c["lasts"] == "कई महीने":
            continue
        row = f"**{_name(item)}** — स्टोरेज: {c['store']}. कितना चलेगा: {c['lasts']}. ख़राब होने के साइन: {c['spoil']}."
        if c["use_up"]:
            row += f" पुराना हो तो: {c['use_up']}."
        lines.append(row)
    dry = [_name(i) for i, c in kn.ITEM_CARE.items() if c["lasts"] in ("कई महीने",) or c["lasts"].startswith("2–3 महीने")]
    return _md(
        "इन्ग्रीडिएंट केयर और यूज़-अप",
        ("सेफ़्टी रूल", "बदबू, चिपचिपापन, फफूंद या कड़वा टेस्ट हो तो चीज़ न पकाएँ; फेंक दें और मैडम/सर को बताएँ. शक हो तो यूज़ न करें."),
        ("फ़्रेश आइटम्स", lines),
        ("ड्राई आइटम्स", ["एयरटाइट डिब्बे में, सूखी जगह; कीड़े, जाले, नमी या बदबू हो तो उतना हिस्सा फेंक दें: " + ", ".join(dry)]),
        ("याद रखें", "आज कौन-सी चीज़ जल्दी ख़राब होगी, यह हर कॉल की शुरुआत में बताया जाता है — यहाँ सिर्फ़ तरीका है."),
    )


def doc_taste_guide() -> str:
    lines = [f"**{_name(i)}** — {c['taste']}" for i, c in kn.ITEM_CARE.items() if c["taste"]]
    tips = [f"{RECIPES[r]['hi']}: {t}" for r, t in kn.DISH_TIPS.items()]
    return _md("टेस्ट गाइड",
               ("आइटम की कंडीशन के हिसाब से", lines), ("कुछ डिशेज़ के लिए", tips),
               ("नोट", "ये टिप्स हैं, रूल नहीं. आपका एक्सपीरियंस और घर की पसंद पहले."))


def doc_health(prefs: dict) -> str:
    items = [f"**{_name(i)}** — {c['health']}" for i, c in kn.ITEM_CARE.items() if c["health"]]
    house = [f"{m['name']}: " + "; ".join(prof.member_instructions(m)) for m in prof.members(prefs)
             if m.get("health") or m.get("notes")]
    return _md(
        "हेल्थ नोट्स",
        ("ये क्या है", "जनरल न्यूट्रिशन की जानकारी है, डॉक्टर की एडवाइस नहीं. डॉक्टर ने जो बताया हो वही सबसे ऊपर है."),
        ("बैलेंस्ड थाली", ["दाल या प्रोटीन + सब्ज़ी + रोटी/राइस + दही या सलाद", "एक ही टाइप की चीज़ें (जैसे सिर्फ़ राइस-आलू) न रखें",
                         "ऑयल-घी-सॉल्ट-शुगर नापकर डालें"]),
        ("फ़ैमिली के लिए इंस्ट्रक्शन", house or ["कोई स्पेशल इंस्ट्रक्शन नहीं"]),
        ("हर आइटम का हेल्थ रोल", items),
        ("बच्चे और एल्डर्स", ["बच्चों के लिए माइल्ड मसाला, छोटे पीस, अच्छी तरह पका हुआ", "एल्डर्स के लिए सॉफ़्ट, लाइट और फ़्रेश खाना"]),
    )


def doc_kitchen(prefs: dict) -> str:
    k = prefs.get("kitchen", {})
    setup = []
    if k.get("burners"):
        setup.append(f"बर्नर: {k['burners']}")
    if k.get("cooker_litres"):
        setup.append(f"प्रेशर कुकर: {k['cooker_litres']} लीटर")
    setup += k.get("notes", [])
    return _md(
        "किचन और इमरजेंसी",
        ("किचन सेटअप", setup or ["रजिस्टर्ड नहीं"]),
        ("गैस की स्मेल आए", ["रेगुलेटर बंद करें", "विंडो-दरवाज़े खोल दें", "इलेक्ट्रिक स्विच, माचिस, लाइटर — कुछ न जलाएँ या दबाएँ",
                           "घर से बाहर निकलकर मैडम/सर को कॉल करें; एलपीजी इमरजेंसी नंबर 1906 (यूज़ करने से पहले वेरिफ़ाई करें)"]),
        ("आग लगे", ["छोटी आग पर ढक्कन या गीला मोटा कपड़ा डालें; ऑयल फ़ायर पर पानी कभी नहीं", "बड़ी आग हो तो बाहर निकलें और 101 पर कॉल करें"]),
        ("बर्न या कट", ["जले हुए हिस्से को 10 मिनट ठंडे बहते पानी में रखें; बटर या टूथपेस्ट न लगाएँ", "गहरा कट या बर्न ज़्यादा हो तो मैडम/सर को बताएँ और 112/102 पर कॉल करें"]),
        ("कोई अप्लायंस ख़राब हो जाए", "बताएँ — कॉल पर 'cook_problem' से आज का मेन्यू उसी हिसाब से बदल दिया जाएगा."),
    )


def doc_rules() -> str:
    table = ["| वो क्या कहती हैं | मतलब | आपको क्या करना है |", "|---|---|---|"]
    table += [f"| {a} | {b} | {c} |" for a, b, c in kn.PHRASEBOOK]
    return _md(
        "बातचीत के रूल्स और फ़्रेज़बुक",
        ("क्या बता सकते हैं", ["आज का मेन्यू, कितने लोग, क्या पहले यूज़ करना है, कॉशन, टेस्ट टिप्स"]),
        ("क्या कभी नहीं", ["पैसे, प्राइस, पेमेंट, ऑर्डर, दुकान, डिलीवरी टाइम", "मेन्यू के बाहर के सामान की मात्रा", "किसी की बीमारी या पर्सनल इन्फ़ो",
                          "अपनी तरफ़ से चेंज या प्रॉमिस — 'मैं मैडम/सर से पूछकर बताती हूँ' कहें"]),
        ("टोन", ["रिस्पेक्ट से, 'आप' कहकर, छोटे सेंटेंस में", "एक टाइम पर एक ही बात; जवाब का वेट करें"]),
        ("जब आवाज़ क्लियर न हो", "एक बार रिपीट करने को कहें; फिर भी क्लियर न हो तो मैसेज भेजने का ऑप्शन दें. कभी अंदाज़े से रिकॉर्ड न करें."),
        ("सेंटेंस के एग्ज़ाम्पल", table),
    )


def doc_units(prefs: dict) -> str:
    u = {**kn.DEFAULT_UNITS, **prefs.get("units", {})}
    return _md(
        "यूनिट्स",
        ("घर की कटोरी", [f"1 कटोरी = लगभग {u['katori_ml']} एमएल (इस घर की कटोरी के हिसाब से)", f"1 गिलास = लगभग {u['glass_ml']} एमएल",
                       f"छोटा चम्मच = {u['chammach_ml']} एमएल; बड़ा चम्मच = {u['badi_chammach_ml']} एमएल"]),
        ("अंदाज़ा", ["रोटी: आम तौर पर 2–3 प्रति बड़ा व्यक्ति, बच्चे को 1–2", "पक्का नहीं हो तो कॉल पर बताई गई क्वांटिटी मानें"]),
        ("क्वांटिटी बताते समय", "अगर वे कटोरी में बताएँ तो ऊपर की नाप से एमएल में बदलकर दोहराएँ और पूछें 'सही है?'"),
    )


def build_docs(prefs: dict, family: int = 4) -> dict[str, str]:
    return {
        "01_ghar_ka_parichay.md": doc_household(prefs, family),
        "02_allergy_aur_suraksha.md": doc_allergy(prefs),
        "03_swaad_aur_pasand.md": doc_taste(prefs),
        "04_saaman_ki_dekhbhal.md": doc_care(),
        "05_swaad_ka_guide.md": doc_taste_guide(),
        "06_sehat.md": doc_health(prefs),
        "07_rasoi_aur_aapatkal.md": doc_kitchen(prefs),
        "08_baat_karne_ke_niyam.md": doc_rules(),
        "09_naap_tol.md": doc_units(prefs),
    }


def build_faqs(prefs: dict, limit: int = 100) -> list[dict]:
    """Exact-answer Q&A (Gnani allows 100 per agent, up to 10 question variants each). Safety first."""
    faqs: list[dict] = []
    for m in prof.members(prefs):
        for g in m.get("allergies", []):
            a = ALLERGENS[g]["hi"]
            faqs.append({"questions": [f"क्या {m['name']} को {a} दे सकते हैं?", f"{m['name']} के खाने में {a} डाल दूँ?",
                                       f"{m['name']} के टिफ़िन में {a} चलेगा?", f"{a} थोड़ी सी डाल दूँ तो?"],
                         "answer": f"नहीं. {m['name']} को {a} से एलर्जी है. बिलकुल नहीं डालनी — थोड़ी भी नहीं, तड़के या सजावट में भी नहीं."})
    faqs.append({"questions": ["गैस की स्मेल आ रही है", "गैस लीक हो रही है", "सिलेंडर से स्मेल आ रही है"],
                 "answer": "रेगुलेटर बंद करें, विंडो-दरवाज़े खोलें, कोई स्विच या माचिस न जलाएँ, बाहर निकलकर मैडम/सर को और 1906 पर कॉल करें."})
    faqs.append({"questions": ["किसी को एलर्जी रिएक्शन हो रहा है", "बच्चे का चेहरा सूज रहा है", "खाने के बाद साँस लेने में प्रॉब्लम है"],
                 "answer": "खिलाना बंद करें, तुरंत मैडम/सर को कॉल करें और 112 पर कॉल करें. पेशेंट को अकेला न छोड़ें."})
    faqs.append({"questions": ["सब्ज़ी से स्मेल आ रही है, यूज़ कर लूँ?", "चिपचिपी हो गई है, पका लूँ?", "फफूंद लगी है, काटकर यूज़ करूँ?"],
                 "answer": "नहीं. बदबू, चिपचिपापन या फफूंद हो तो वो चीज़ न पकाएँ, फेंक दें और मैडम/सर को बताएँ."})
    u = {**kn.DEFAULT_UNITS, **prefs.get("units", {})}
    faqs.append({"questions": ["एक कटोरी कितनी होती है?", "कटोरी कितने एमएल की?"],
                 "answer": f"इस घर की एक कटोरी लगभग {u['katori_ml']} एमएल की है."})
    st = prof.style_instructions(prefs)
    if st:
        faqs.append({"questions": ["मसाला कितना डालूँ?", "घर में कैसा टेस्ट पसंद है?", "ऑयल-सॉल्ट कितना रखूँ?"], "answer": "; ".join(st) + "."})
    for item, c in kn.ITEM_CARE.items():
        if len(faqs) >= limit:
            break
        if c["use_up"]:
            n = _name(item)
            ans = c["use_up"] + (f". सबसे अच्छा: {c['taste']}" if c["taste"] else "")
            faqs.append({"questions": [f"{n} पुराना हो गया है, क्या करूँ?", f"{n} ज़्यादा पक गया है", f"{n} का क्या करूँ, जल्दी ख़राब होगा"],
                         "answer": ans + ". बदबू या चिपचिपापन हो तो फेंक दें."})
    return faqs[:limit]


def write(out_dir, prefs: dict, family: int = 4, docs: dict | None = None, faqs: list | None = None) -> list[str]:
    """Write the knowledge base. `docs`/`faqs` carry the owner's Studio edits; without them, the generated defaults."""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for name, text in (docs if docs is not None else build_docs(prefs, family)).items():
        (out / name).write_text(text, encoding="utf-8")
        names.append(name)
    (out / "faqs.json").write_text(json.dumps(faqs if faqs is not None else build_faqs(prefs), ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    return names + ["faqs.json"]
