"""What the cook may not know: how long things last, the signs they've gone, how to use them as they age, what tastes
best, and the plain health value of an ingredient.

Language: Hindi in Devanagari with everyday English words (फ्रिज, स्टोरेज, एक्सपायरी, यूज़, टेस्ट), the way people actually
speak at home, and what Gnani's Hindi voice reads most naturally. Cook-facing and deliberately conservative.

Not here: recipes (she knows them), and anything that changes daily (stock, use-by dates, who is eating). Those
arrive per call as variables.

Health lines are general nutrition, not medical advice, and never name a person's condition.
"""
from __future__ import annotations

from .recipes import ITEMS, RECIPES

DRY = dict(store="एयरटाइट डिब्बे में, ड्राई और ठंडी जगह पर", lasts="कई महीने",
           spoil="कीड़े या जाले, नमी, अजीब स्मेल — ऐसा हो तो उतना हिस्सा फेंक दें और मैडम/सर को बताएँ",
           use_up="", taste="")

# store = स्टोरेज · lasts = शेल्फ लाइफ · spoil = ख़राब होने के साइन · use_up = पुराना होने पर क्या करें
# taste = कब/किसमें बेस्ट · health = हेल्थ के लिए (जनरल जानकारी)
ITEM_CARE: dict[str, dict] = {
    "tomato": dict(store="रूम टेम्परेचर पर, धूप से दूर; बहुत पके हों तो फ्रिज में", lasts="3–5 दिन",
                   spoil="फफूंद, रस टपकना, खट्टी स्मेल — फेंक दें",
                   use_up="ओवर-रिप टमाटर की प्यूरी बनाकर दाल या ग्रेवी में डालें",
                   taste="ज़्यादा पके टमाटर मीठे और जूसी होते हैं — दाल, ग्रेवी और चटनी में बेस्ट; सलाद के लिए कड़क टमाटर यूज़ करें",
                   health="विटामिन सी और लाइकोपीन"),
    "onion": dict(store="ड्राई, हवादार जगह पर; आलू के साथ नहीं", lasts="2–3 हफ़्ते",
                  spoil="गीला, बहुत सॉफ्ट, काली फफूंद या स्मेल — सड़ा हिस्सा फेंक दें",
                  use_up="हल्का स्प्राउट आया हो तो चलेगा, अगर प्याज़ टाइट है और स्मेल नहीं है",
                  taste="पका हुआ प्याज़ ग्रेवी की स्वीटनेस बढ़ाता है", health="खाने का टेस्ट बढ़ाता है, फाइबर"),
    "potato": dict(store="अँधेरी, ठंडी, ड्राई जगह पर; प्याज़ से अलग", lasts="2–3 हफ़्ते",
                   spoil="हरा कलर, ज़्यादा स्प्राउट, सॉफ्ट या सड़ा हुआ",
                   use_up="हरे हिस्से या ज़्यादा स्प्राउट वाले आलू न खाएँ (हानिकारक हो सकते हैं); हल्के स्प्राउट पूरी तरह काटकर निकालें",
                   taste="पुराने आलू पराठे और स्टफिंग में अच्छे; नए आलू जीरा-आलू में", health="एनर्जी और पोटैशियम; उबालकर या भूनकर बेहतर, फ्राई कम"),
    "spinach": dict(store="बिना धोए, पेपर में लपेटकर फ्रिज में", lasts="2–3 दिन",
                    spoil="पीला पड़ना, चिपचिपापन, स्मेल — फेंक दें",
                    use_up="मुरझाया हो पर चिपचिपा न हो तो आज ही ब्लांच करके पका लें",
                    taste="फ्रेश पालक सबसे ग्रीन और मीठा; मुरझाया हो तो ब्लांच करें और ज़्यादा न पकाएँ",
                    health="आयरन, फोलेट और विटामिन के"),
    "paneer": dict(store="फ्रिज में, पानी में डुबोकर (रोज़ पानी बदलें)", lasts="खुलने के बाद 3–5 दिन, या पैकेट की डेट तक",
                   spoil="खट्टी स्मेल, चिपचिपापन, पीली परत — फेंक दें",
                   use_up="थोड़ा टाइट हो गया पनीर 10 मिनट गुनगुने पानी में रखें, सॉफ्ट हो जाएगा; भुर्जी या ग्रेवी में डालें",
                   taste="पुराना पनीर फ्राई करने की जगह भुर्जी या ग्रेवी में अच्छा; पनीर लास्ट में डालें ताकि टाइट न हो",
                   health="प्रोटीन और कैल्शियम"),
    "cauliflower": dict(store="फ्रिज में, ड्राई रखें", lasts="4–5 दिन", spoil="काले धब्बे फैलना, चिपचिपापन, स्मेल",
                        use_up="छोटे काले धब्बे काट दें; डंठल और सॉफ्ट पत्ते भी सब्ज़ी में डाल सकते हैं",
                        taste="फ्रेश गोभी भूनकर क्रिस्पी; थोड़ी पुरानी हो तो ग्रेवी या पराठे की स्टफिंग में", health="फाइबर और विटामिन सी"),
    "peas": dict(store="फ्रिज में; ज़्यादा हों तो फ्रीज़र में", lasts="5–6 दिन फ्रेश, फ्रीज़र में महीनों", spoil="चिपचिपापन, स्मेल, फफूंद",
                 use_up="ज़्यादा हों तो उबालकर फ्रीज़र में रख दें", taste="फ्रेश मटर मीठे होते हैं; ज़्यादा न पकाएँ", health="प्रोटीन और फाइबर"),
    "dal": dict(DRY, health="प्रोटीन और फाइबर"),
    "rice": dict(DRY, health="एनर्जी देता है; साथ में दाल-सब्ज़ी रखें"),
    "atta": dict(DRY, lasts="2–3 महीने", health="फाइबर; मोटा पिसा आटा बेहतर"),
    "curd": dict(store="फ्रिज में", lasts="5–7 दिन", spoil="फफूंद, गुलाबी या हरी परत, कड़वी स्मेल — फेंक दें",
                 use_up="खट्टा हो गया पर फफूंद नहीं है तो कढ़ी, मैरिनेशन या पराठे के आटे में लगाएँ",
                 taste="खट्टा दही कढ़ी में सबसे बेस्ट; फ्रेश दही रायते और दही-चावल में", health="डाइजेशन के लिए अच्छा, कैल्शियम"),
    "cream": dict(store="फ्रिज में", lasts="खुलने के बाद 3–4 दिन", spoil="खट्टी स्मेल, फटा हुआ — फेंक दें",
                  use_up="कम क्वांटिटी में पालक या पनीर की ग्रेवी में डालें", taste="लास्ट में डालें, उबालें नहीं", health="हेवी है — कम क्वांटिटी रखें"),
    "rajma": dict(DRY, health="प्रोटीन और फाइबर; रात भर भिगोकर अच्छी तरह उबालें"),
    "cucumber": dict(store="फ्रिज में", lasts="4–5 दिन", spoil="बहुत सॉफ्ट, चिपचिपा, कड़वा — कड़वा हो तो फेंक दें",
                     use_up="सॉफ्ट हो गया हो तो बीज निकालकर रायते में", taste="कड़क खीरा सलाद में; सॉफ्ट वाला रायते में", health="पानी ज़्यादा, ठंडक देता है"),
    "milk": dict(store="उबालकर फ्रिज में", lasts="उबालने के बाद 1–2 दिन", spoil="फटना, खट्टी स्मेल",
                 use_up="फटे दूध से घर का पनीर बना सकते हैं, पर स्मेल हो तो फेंक दें", taste="", health="कैल्शियम"),
    "egg": dict(store="फ्रिज में", lasts="3–4 हफ़्ते", spoil="फोड़ने पर स्मेल; पानी में तैरे तो बहुत पुराना",
                use_up="पुराने एग अच्छी तरह पूरा पकाकर यूज़ करें", taste="", health="प्रोटीन; हमेशा पूरा पका हुआ"),
    "chicken": dict(store="फ्रिज के सबसे ठंडे हिस्से में, अलग डिब्बे में", lasts="1–2 दिन", spoil="स्मेल, चिपचिपापन, हरा-भूरा कलर",
                    use_up="पैकेट की एक्सपायरी डेट के बाद यूज़ न करें — फेंक दें; कच्चे चिकन के बर्तन और बोर्ड अलग धोएँ, अच्छी तरह पकाएँ",
                    taste="फ्रेश चिकन जल्दी गलता है, ज़्यादा न पकाएँ", health="प्रोटीन; स्किन हटाकर हल्का"),
    "bhindi": dict(store="ड्राई, कपड़े या पेपर में; गीली न रखें", lasts="2–3 दिन", spoil="चिपचिपापन, काले धब्बे, सॉफ्ट",
                   use_up="सॉफ्ट हो गई तो आज ही बनाएँ", taste="धोकर पूरी तरह सुखाकर काटें — चिपचिपापन कम होगा", health="फाइबर"),
    "brinjal": dict(store="ठंडी जगह पर, या फ्रिज में", lasts="4–5 दिन", spoil="झुर्रियाँ, सॉफ्ट सड़े धब्बे",
                    use_up="छोटे धब्बे काट दें", taste="भर्ते के लिए भूनें; फ्रेश बैंगन में बीज कम होते हैं", health="फाइबर"),
    "cabbage": dict(store="फ्रिज में", lasts="1 हफ़्ता", spoil="सड़ी स्मेल, चिपचिपी पत्तियाँ", use_up="ऊपर की ख़राब पत्तियाँ हटा दें",
                    taste="हल्का पकाएँ, क्रंच बना रहे", health="फाइबर और विटामिन सी"),
    "carrot": dict(store="फ्रिज में", lasts="1–2 हफ़्ते", spoil="फफूंद, चिपचिपापन",
                   use_up="रबर जैसी सॉफ्ट हो गई हो तो 30 मिनट ठंडे पानी में डुबोएँ, क्रिस्पी हो जाएगी", taste="मीठी; मटर के साथ अच्छी", health="विटामिन ए (बीटा-कैरोटीन)"),
    "beans": dict(store="फ्रिज में", lasts="3–4 दिन", spoil="चिपचिपापन, काले धब्बे", use_up="पुरानी फली के रेशे निकाल दें", taste="ज़्यादा न पकाएँ", health="फाइबर"),
    "capsicum": dict(store="फ्रिज में", lasts="5–6 दिन", spoil="बहुत सॉफ्ट, काले धब्बे", use_up="झुर्रीदार हो तो आज ही पकाएँ", taste="लास्ट में डालें ताकि क्रिस्पी रहे", health="विटामिन सी"),
    "lauki": dict(store="फ्रिज में", lasts="4–5 दिन", spoil="सॉफ्ट सड़े धब्बे, स्मेल",
                  use_up="काटकर चखें — अगर कड़वी लगे तो पूरी फेंक दें, बिलकुल न पकाएँ (कड़वी लौकी हानिकारक हो सकती है)",
                  taste="हल्की सब्ज़ी; टमाटर के साथ अच्छी", health="हल्की और पचने में आसान, पानी ज़्यादा"),
    "mushroom": dict(store="पेपर बैग में फ्रिज में, बिना धोए", lasts="2–3 दिन", spoil="चिपचिपापन, काले धब्बे, स्मेल — फेंक दें",
                     use_up="जल्दी पकाएँ; चिपचिपे मशरूम न खाएँ", taste="तेज़ आँच पर जल्दी भूनें", health="प्रोटीन और विटामिन बी"),
    "moong": dict(DRY, health="आसानी से पचने वाली दाल"),
    "masoor": dict(DRY, health="प्रोटीन और आयरन"),
    "chana": dict(DRY, health="प्रोटीन और फाइबर; भिगोकर अच्छी तरह उबालें"),
    "besan": dict(DRY, lasts="2–3 महीने", health="प्रोटीन; फ्राई करने पर हेवी हो जाता है"),
    "poha": dict(DRY, health="हल्का ब्रेकफास्ट; सब्ज़ी डालें तो और अच्छा"),
    "suji": dict(DRY, lasts="2–3 महीने", health="हल्का; सब्ज़ी डालें"),
    "bread": dict(store="ड्राई जगह पर, फ्रिज में नहीं", lasts="3–4 दिन", spoil="हरी या सफ़ेद फफूंद — पूरा पैकेट देखें और फेंक दें",
                  use_up="बासी (पर फफूंद नहीं) ब्रेड से टोस्ट, उपमा या ब्रेड-पकोड़े बनाएँ", taste="बासी ब्रेड सेंकने पर क्रिस्पी अच्छी", health="मैदे की जगह होल-व्हीट बेहतर"),
    "sabudana": dict(DRY, health="एनर्जी देता है, प्रोटीन कम — मूंगफली या दही साथ दें"),
    "kuttu": dict(DRY, lasts="1–2 महीने", health="व्रत में चलता है, पचने में हल्का"),
    "samak": dict(DRY, health="व्रत में चलता है, हल्का"),
    "peanuts": dict(DRY, health="प्रोटीन और गुड फैट — पर एलर्जी हो तो बिलकुल नहीं"),
    "banana": dict(store="रूम टेम्परेचर पर", lasts="3–4 दिन", spoil="बहुत काला, रस टपकना, स्मेल",
                   use_up="बहुत पके केले से पराठा, शेक या हलवा", taste="पके केले मीठे — मीठी डिशेज़ में सबसे बेस्ट", health="एनर्जी और पोटैशियम"),
    "apple": dict(store="फ्रिज में", lasts="1–2 हफ़्ते", spoil="सड़े सॉफ्ट धब्बे, फफूंद", use_up="सॉफ्ट धब्बे काटकर निकाल दें", taste="कड़क सेब चाट में", health="फाइबर"),
}
ITEM_CARE = {k: {**dict(store="", lasts="", spoil="", use_up="", taste="", health=""), **v} for k, v in ITEM_CARE.items()}
assert set(ITEM_CARE) == set(ITEMS), set(ITEMS) ^ set(ITEM_CARE)

# Taste/health tips for specific dishes, only where today's ingredient state or this dish needs a nudge.
DISH_TIPS: dict[str, str] = {
    "palak_paneer": "पालक को ब्लांच करके पीसें, कलर ग्रीन रहेगा; क्रीम कम और लास्ट में; पनीर आख़िरी 3–4 मिनट ही पकाएँ",
    "tomato_dal": "टमाटर को पूरी तरह गलने दें; पके टमाटर यहाँ सबसे अच्छे लगते हैं",
    "dal_tadka": "तड़का लास्ट में डालें और तुरंत ढक दें",
    "palak_dal": "पालक लास्ट में डालें ताकि कलर बना रहे",
    "matar_paneer": "मटर को ज़्यादा न पकाएँ; पनीर लास्ट में",
    "aloo_gobi": "गोभी और आलू को ज़्यादा हिलाएँ नहीं, टूट जाएँगे",
    "bhindi_masala": "भिंडी पूरी सुखाकर काटें और ढककर न पकाएँ",
    "baingan_bharta": "बैंगन को सीधी आँच पर भूनें, स्मोकी टेस्ट आएगा",
    "kadhi": "खट्टा दही कढ़ी के लिए सबसे बेस्ट; उबाल आने तक चलाते रहें",
    "kheera_raita": "सॉफ्ट खीरे का पानी निचोड़ दें",
    "poha": "पोहा को ज़्यादा भिगोएँ नहीं",
    "aloo_paratha": "स्टफिंग ठंडी करके भरें; पुराने आलू यहाँ अच्छे हैं",
    "moong_khichdi": "हल्की और पचने में आसान — बीमार या सीनियर के लिए अच्छी",
    "rajma": "रात भर भिगोए राजमा अच्छी तरह उबालें, कच्चा न रहे",
    "chole": "रात भर भिगोए चने अच्छी तरह उबालें, कच्चे न रहें",
}

COURSE_TIPS = {"sabzi": "सब्ज़ी को ज़्यादा न गलाएँ", "dal": "दाल गाढ़ी-पतली घर की पसंद के हिसाब से रखें",
               "one_pot": "साथ में दही या सलाद दें", "breakfast": "गरमागरम सर्व करें", "side": "ठंडा सर्व करें", "carb": "",
               "vrat": "व्रत के रूल्स का ध्यान रखें"}

MEAL_HI = {"breakfast": "ब्रेकफास्ट", "lunch": "लंच", "dinner": "डिनर"}


def hi_name(item: str) -> str:
    return ITEMS[item]["hi"]


def when_hi(days_left: int | None) -> str:
    """Days until use-by relative to the cooking day -> how to say it to the cook."""
    if days_left is None:
        return ""
    if days_left <= 0:
        return "आज ही यूज़ कर लें"
    if days_left == 1:
        return "कल तक चलेगा, आज यूज़ कर लेना अच्छा रहेगा"
    return f"{days_left} दिन और चलेगा"


def qty_hi(qty: float, unit: str) -> str:
    q = int(qty) if float(qty).is_integer() else round(qty, 1)
    if unit == "g":
        return f"{q / 1000:g} किलो" if q >= 1000 else f"{q} ग्राम"
    if unit == "ml":
        return f"{q / 1000:g} लीटर" if q >= 1000 else f"{q} मि.ली."
    return f"{q}"


def dish_health_note(recipe_ids: list[str]) -> str:
    """Plain, qualitative health note for a menu: what it gives and what is missing."""
    bits, seen = [], set()
    for rid in recipe_ids:
        for item in RECIPES[rid]["needs"]:
            h = ITEM_CARE[item]["health"]
            if h and item not in seen and item not in ("rice", "atta", "onion", "tomato", "milk"):
                seen.add(item)
                bits.append(f"{hi_name(item)}: {h}")
    courses = {RECIPES[r]["course"] for r in recipe_ids}
    if {"dal", "sabzi", "carb"} <= courses or ({"one_pot"} & courses and "side" in courses):
        bits.append("प्लेट बैलेंस्ड है")
    elif courses & {"one_pot", "breakfast"} and "side" not in courses:
        bits.append("साथ में दही या सलाद दें, प्लेट बैलेंस्ड रहेगी")
    if any("heavy" in RECIPES[r]["tags"] for r in recipe_ids):
        bits.append("मेन्यू थोड़ा हेवी है — ऑयल-घी कम रखें")
    return "; ".join(bits[:4])


def dish_tips(recipe_ids: list[str]) -> list[str]:
    out = []
    for rid in recipe_ids:
        t = DISH_TIPS.get(rid) or COURSE_TIPS.get(RECIPES[rid]["course"], "")
        if t:
            out.append(f"{RECIPES[rid]['hi']}: {t}")
    return out


# ---- units: a household can calibrate its own katori
DEFAULT_UNITS = {"katori_ml": 150, "glass_ml": 200, "chammach_ml": 5, "badi_chammach_ml": 15}

# (what the cook says, what it means, what to do) — plain examples for the phrasebook document
PHRASEBOOK = [
    ("पनीर खत्म हो गया", "पनीर पूरा ख़त्म", "रिपीट करके कन्फर्म करें 'पनीर पूरा ख़त्म हो गया, सही?' — हाँ कहे तभी रिकॉर्ड करें"),
    ("2 टमाटर बचे हैं", "2 टमाटर बचे हैं", "रिपीट करें 'दो टमाटर बचे हैं, सही?'"),
    ("टमाटर कम हैं", "कम है, कितना पता नहीं", "पूछें 'अंदाज़न कितने बचे हैं?'; क्वांटिटी न बताए तो 'कम' रिकॉर्ड करें"),
    ("गैस नहीं जल रही / सिलेंडर खत्म", "स्टोव काम नहीं कर रहा", "पहले पूछें 'गैस की स्मेल तो नहीं आ रही?' (स्मेल हो तो इमरजेंसी स्टेप्स); फिर बिना स्टोव वाला ऑप्शन"),
    ("कुकर खराब है", "प्रेशर कुकर नहीं चल रहा", "कुकर के बिना बनने वाला मेन्यू दें"),
    ("आज टाइम कम है", "क्विक डिश चाहिए", "30 मिनट से कम वाला ऑप्शन दें"),
    ("सब्ज़ी खराब निकली", "सब्ज़ी सड़ी हुई", "पूछें कौन-सी; सड़ी चीज़ न पकाएँ; मेन्यू बदलें"),
    ("कल नहीं आऊँगी", "कल की छुट्टी", "ठीक है कहें, मैडम/सर को अलर्ट जाएगा; वजह न कुरेदें"),
    ("खाना बन गया", "खाना तैयार", "थैंक्स बोलें; पूछें 'आज क्या कम या ज़्यादा रहा?'"),
    ("पैसे / सामान कब आएगा?", "पैसे या डिलीवरी की बात", "पोलाइटली कहें 'यह मैडम/सर बता देंगे'"),
]
