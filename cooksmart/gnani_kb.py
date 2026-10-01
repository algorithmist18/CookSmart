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
    people = [f"{m['name']} ({prof.AGE_GROUPS.get(m.get('age_group', 'adult'), 'बड़े')})" for m in prof.members(prefs)]
    ins = [f"{m['name']}: " + "; ".join(prof.member_instructions(m)) for m in prof.members(prefs)
           if prof.member_instructions(m)]
    times = [f"{k}: {v}" for k, v in prefs.get("meal_times", {}).items()]
    customs = [c if isinstance(c, str) else c.get("text", "") for c in prefs.get("customs", [])]
    return _md(
        "घर का परिचय (Household profile)",
        ("कौन खाता है", [f"रोज़ लगभग {family} लोग खाते हैं. मेहमान हों तो हर कॉल में बताया जाएगा कि आज कितने लोग हैं."]
         + (["घर के लोग: " + ", ".join(people)] if people else [])),
        ("हर व्यक्ति के लिए निर्देश", ins or ["कोई विशेष निर्देश नहीं"]),
        ("खाने का समय", times or ["तय नहीं"]),
        ("घर के नियम और रीति-रिवाज", [c for c in customs if c] or ["कोई विशेष नियम नहीं"]),
        ("ज़रूरी", "यहाँ सिर्फ़ निर्देश लिखे हैं. किसी की बीमारी या निजी बात पर चर्चा न करें. ज़्यादा जानना हो तो मैडम/सर से पूछने को कहें."),
    )


def doc_allergy(prefs: dict) -> str:
    groups = sorted(prof.allergy_groups(prefs))
    per = []
    for g in groups:
        who = ", ".join(prof.who_is_allergic(prefs, g))
        per.append(f"**{ALLERGENS[g]['hi']}** — {who}. बिलकुल नहीं: न कम, न ज़्यादा, न तड़के में, न सजावट में, न चटनी में.")
    hidden = [
        "बेसन = चना; छोले = चना",
        "ब्रेड में गेहूं होता है, और अक्सर दूध या अंडा भी",
        "पनीर, दही, क्रीम, मक्खन, घी — सब दूध से बनते हैं",
        "बाज़ार के पैकेट वाले मसाले, नमकीन, चटनी, सॉस में मूंगफली या दूध के अंश हो सकते हैं — लेबल पढ़ें, पक्का न हो तो इस्तेमाल न करें",
        "पोहा, उपमा और चाट में मूंगफली अक्सर ऊपर से डाली जाती है — एलर्जी वाले के हिस्से में बिलकुल नहीं",
    ]
    return _md(
        "एलर्जी और सुरक्षा (सबसे ज़रूरी दस्तावेज़)",
        ("प्राथमिकता", "हर कॉल की शुरुआत में बताई गई 'सावधानियाँ' इस दस्तावेज़ से भी ऊपर हैं. शक हो तो चीज़ इस्तेमाल न करें और मैडम/सर से पूछें."),
        ("घर में किसे किससे एलर्जी है", per or ["अभी किसी को एलर्जी दर्ज नहीं है"]),
        ("छिपे हुए स्रोत", hidden),
        ("बचाव के तरीके", ["एलर्जी वाले का खाना पहले और अलग बर्तन में बनाएँ", "अलग चम्मच/कड़छी; इस्तेमाल से पहले साफ़ धोएँ",
                           "मेहमानों के लिए भी वही नियम"]),
        ("अगर किसी को एलर्जी जैसी तकलीफ़ हो (होंठ/चेहरा सूजना, साँस में दिक्कत, चकत्ते, उल्टी)",
         ["तुरंत खिलाना बंद करें", "तुरंत मैडम/सर को फ़ोन करें और 112 पर कॉल करें; साँस की तकलीफ़ में देर न करें",
          "मरीज़ को अकेला न छोड़ें", "यह डॉक्टर की सलाह की जगह नहीं है"]),
    )


def doc_taste(prefs: dict) -> str:
    st = prof.style_instructions(prefs)
    sig = [f"{RECIPES[r]['hi']}: {t}" for r, t in prefs.get("signature", {}).items() if r in RECIPES]
    likes = [_name(i) for i in prefs.get("likes", []) if i in ITEMS]
    dislikes = [_name(i) for i in prefs.get("dislikes", []) if i in ITEMS]
    persons = [f"{m['name']}: " + "; ".join(x for x in prof.member_instructions(m) if "एलर्जी" not in x)
               for m in prof.members(prefs) if any("एलर्जी" not in x for x in prof.member_instructions(m))]
    return _md(
        "इस घर का स्वाद (Taste & personalisation)",
        ("घर की आम पसंद", st or ["सामान्य"]),
        ("हर व्यक्ति की पसंद", persons or ["कोई विशेष नहीं"]),
        ("इस घर के खास तरीके", sig or ["कोई विशेष नहीं"]),
        ("पसंदीदा चीज़ें", [", ".join(likes)] if likes else ["दर्ज नहीं"]),
        ("जो पसंद नहीं", [", ".join(dislikes)] if dislikes else ["दर्ज नहीं"]),
        ("सुझाव", "अगर घर की पसंद और किसी टिप में फ़र्क हो, तो घर की पसंद मानें."),
    )


def doc_care() -> str:
    lines: list[str] = []
    for item, c in kn.ITEM_CARE.items():
        if not c["lasts"] or c["lasts"] == "कई महीने":
            continue
        row = f"**{_name(item)}** — कैसे रखें: {c['store']}. कितना चलेगा: {c['lasts']}. ख़राब होने के संकेत: {c['spoil']}."
        if c["use_up"]:
            row += f" पुराना हो तो: {c['use_up']}."
        lines.append(row)
    dry = [_name(i) for i, c in kn.ITEM_CARE.items() if c["lasts"] in ("कई महीने",) or c["lasts"].startswith("2–3 महीने")]
    return _md(
        "सामान की देखभाल और बचा-खुचा इस्तेमाल (Ingredient care & use-up)",
        ("सुरक्षा का नियम", "बदबू, चिपचिपापन, फफूंद या कड़वा स्वाद हो तो चीज़ न पकाएँ; फेंक दें और मैडम/सर को बताएँ. शक हो तो इस्तेमाल न करें."),
        ("ताज़ा सामान", lines),
        ("सूखा सामान", ["बंद डिब्बे में, सूखी जगह; कीड़े, जाले, नमी या बदबू हो तो उतना हिस्सा फेंक दें: " + ", ".join(dry)]),
        ("ध्यान रखें", "आज कौन-सी चीज़ जल्दी ख़राब होगी, यह हर कॉल की शुरुआत में बताया जाता है — यहाँ सिर्फ़ तरीका है."),
    )


def doc_taste_guide() -> str:
    lines = [f"**{_name(i)}** — {c['taste']}" for i, c in kn.ITEM_CARE.items() if c["taste"]]
    tips = [f"{RECIPES[r]['hi']}: {t}" for r, t in kn.DISH_TIPS.items()]
    return _md("कब क्या सबसे अच्छा लगता है (Taste guide)",
               ("सामान की हालत के हिसाब से", lines), ("कुछ व्यंजनों के लिए", tips),
               ("नोट", "यह सुझाव हैं, नियम नहीं. आपका अनुभव और घर की पसंद पहले."))


def doc_health(prefs: dict) -> str:
    items = [f"**{_name(i)}** — {c['health']}" for i, c in kn.ITEM_CARE.items() if c["health"]]
    house = [f"{m['name']}: " + "; ".join(prof.member_instructions(m)) for m in prof.members(prefs)
             if m.get("health") or m.get("notes")]
    return _md(
        "सेहत की सामान्य जानकारी (Health notes)",
        ("यह क्या है", "सामान्य पोषण की जानकारी है, डॉक्टर की सलाह नहीं. किसी के लिए डॉक्टर ने जो बताया हो वही सर्वोपरि है."),
        ("संतुलित थाली", ["दाल या प्रोटीन + सब्ज़ी + रोटी/चावल + दही या सलाद", "एक ही तरह की चीज़ें (जैसे सिर्फ़ चावल-आलू) न रखें",
                         "तेल-घी-नमक-चीनी नापकर डालें"]),
        ("घर के लोगों के लिए निर्देश", house or ["कोई विशेष निर्देश नहीं"]),
        ("हर सामान की सेहत में भूमिका", items),
        ("छोटे बच्चे और बुज़ुर्ग", ["बच्चों के लिए कम मसाला, छोटे टुकड़े, पूरी तरह पका हुआ", "बुज़ुर्गों के लिए नरम, हल्का और ताज़ा खाना"]),
    )


def doc_kitchen(prefs: dict) -> str:
    k = prefs.get("kitchen", {})
    setup = []
    if k.get("burners"):
        setup.append(f"चूल्हे: {k['burners']}")
    if k.get("cooker_litres"):
        setup.append(f"प्रेशर कुकर: {k['cooker_litres']} लीटर")
    setup += k.get("notes", [])
    return _md(
        "रसोई और आपातकाल (Kitchen & emergencies)",
        ("रसोई की जानकारी", setup or ["दर्ज नहीं"]),
        ("गैस की गंध आए", ["रेगुलेटर बंद करें", "खिड़की-दरवाज़े खोल दें", "बिजली का स्विच, माचिस, लाइटर — कुछ न जलाएँ या दबाएँ",
                           "घर से बाहर निकलकर मैडम/सर को फ़ोन करें; एलपीजी आपातकालीन नंबर 1906 (भेजने से पहले जाँच लें)"]),
        ("आग लगे", ["छोटी आग पर ढक्कन या गीला मोटा कपड़ा डालें; तेल की आग पर पानी कभी नहीं", "बड़ी आग हो तो बाहर निकलें और 101 पर फ़ोन करें"]),
        ("जल जाएँ या कट जाएँ", ["जले हुए हिस्से को 10 मिनट ठंडे बहते पानी में रखें; मक्खन या टूथपेस्ट न लगाएँ", "गहरा कट या जलन ज़्यादा हो तो मैडम/सर को बताएँ और 112/102 पर फ़ोन करें"]),
        ("कोई उपकरण ख़राब हो जाए", "बताएँ — कॉल पर 'cook_problem' से आज का मेन्यू उसी हिसाब से बदल दिया जाएगा."),
    )


def doc_rules() -> str:
    table = ["| वह क्या कहती हैं | मतलब | आपको क्या करना है |", "|---|---|---|"]
    table += [f"| {a} | {b} | {c} |" for a, b, c in kn.PHRASEBOOK]
    return _md(
        "बात करने के नियम (Boundaries & phrasebook)",
        ("क्या बता सकते हैं", ["आज का मेन्यू, कितने लोग, किस चीज़ से शुरू करें, क्या पहले इस्तेमाल करना है, सावधानियाँ, स्वाद के सुझाव"]),
        ("क्या कभी नहीं", ["पैसे, कीमत, भुगतान, ऑर्डर, दुकान, डिलीवरी का समय", "मेन्यू के बाहर के सामान की मात्रा", "किसी की बीमारी या निजी जानकारी",
                          "अपनी तरफ़ से बदलाव या वादा — 'मैं मैडम/सर से पूछकर बताती हूँ' कहें"]),
        ("लहजा", ["सम्मान से, 'आप' कहकर, छोटे वाक्यों में", "एक बार में एक ही बात; जवाब का इंतज़ार करें"]),
        ("जब बात साफ़ न सुनाई दे", "एक बार दोहराने को कहें; फिर भी साफ़ न हो तो संदेश भेजने का विकल्प दें. कभी अंदाज़े से दर्ज न करें."),
        ("वाक्यों के उदाहरण", table),
    )


def doc_units(prefs: dict) -> str:
    u = {**kn.DEFAULT_UNITS, **prefs.get("units", {})}
    return _md(
        "नाप-तोल (Units)",
        ("घर की कटोरी", [f"1 कटोरी = लगभग {u['katori_ml']} मि.ली. (इस घर की कटोरी के हिसाब से)", f"1 गिलास = लगभग {u['glass_ml']} मि.ली.",
                       f"छोटा चम्मच = {u['chammach_ml']} मि.ली.; बड़ा चम्मच = {u['badi_chammach_ml']} मि.ली."]),
        ("अंदाज़ा", ["रोटी: आम तौर पर 2–3 प्रति बड़ा व्यक्ति, बच्चे को 1–2", "पक्का नहीं हो तो कॉल पर बताई गई सामग्री की मात्रा मानें"]),
        ("मात्रा बताते समय", "अगर वे कटोरी में बताएँ तो ऊपर की नाप से मि.ली. में बदलकर दोहराएँ और पूछें 'सही है?'"),
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
    faqs.append({"questions": ["गैस की गंध आ रही है", "गैस लीक हो रही है", "सिलेंडर से बदबू आ रही है"],
                 "answer": "रेगुलेटर बंद करें, खिड़की-दरवाज़े खोलें, कोई स्विच या माचिस न जलाएँ, बाहर निकलकर मैडम/सर को और 1906 पर फ़ोन करें."})
    faqs.append({"questions": ["किसी को एलर्जी जैसी तकलीफ़ हो रही है", "बच्चे का चेहरा सूज रहा है", "खाने के बाद साँस लेने में दिक्कत है"],
                 "answer": "खिलाना बंद करें, तुरंत मैडम/सर को फ़ोन करें और 112 पर कॉल करें. मरीज़ को अकेला न छोड़ें."})
    faqs.append({"questions": ["सब्ज़ी से बदबू आ रही है, चला लूँ?", "चिपचिपी हो गई है, पका लूँ?", "फफूंद लगी है, काटकर इस्तेमाल करूँ?"],
                 "answer": "नहीं. बदबू, चिपचिपापन या फफूंद हो तो वह चीज़ न पकाएँ, फेंक दें और मैडम/सर को बताएँ."})
    u = {**kn.DEFAULT_UNITS, **prefs.get("units", {})}
    faqs.append({"questions": ["एक कटोरी कितनी होती है?", "कटोरी कितने मि.ली. की?"],
                 "answer": f"इस घर की एक कटोरी लगभग {u['katori_ml']} मि.ली. की है."})
    st = prof.style_instructions(prefs)
    if st:
        faqs.append({"questions": ["मसाला कितना डालूँ?", "घर में कैसा स्वाद पसंद है?", "तेल-नमक कितना रखूँ?"], "answer": "; ".join(st) + "."})
    for item, c in kn.ITEM_CARE.items():
        if len(faqs) >= limit:
            break
        if c["use_up"]:
            n = _name(item)
            ans = c["use_up"] + (f". सबसे अच्छा: {c['taste']}" if c["taste"] else "")
            faqs.append({"questions": [f"{n} पुराना हो गया है, क्या करूँ?", f"{n} ज़्यादा पक गया है", f"{n} का क्या करूँ, जल्दी ख़राब होगा"],
                         "answer": ans + ". बदबू या चिपचिपापन हो तो फेंक दें."})
    return faqs[:limit]


def write(out_dir, prefs: dict, family: int = 4) -> list[str]:
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    names = []
    for name, text in build_docs(prefs, family).items():
        (out / name).write_text(text, encoding="utf-8")
        names.append(name)
    (out / "faqs.json").write_text(json.dumps(build_faqs(prefs), ensure_ascii=False, indent=2), encoding="utf-8")
    return names + ["faqs.json"]
