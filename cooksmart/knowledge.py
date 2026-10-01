"""What the cook may not know: how long things last, the signs they've gone, how to use them as they age, what tastes
best, and the plain health value of an ingredient. All Hindi, cook-facing, deliberately conservative.

Not here: recipes (she knows them), and anything that changes daily (stock, use-by dates, who is eating). Those
arrive per call as variables.

Health lines are general nutrition, not medical advice, and never name a person's condition.
"""
from __future__ import annotations

from .recipes import ITEMS, RECIPES

DRY = dict(store="बंद डिब्बे में, सूखी और ठंडी जगह", lasts="कई महीने",
           spoil="कीड़े या जाले, नमी, अजीब बदबू — ऐसा हो तो उतना हिस्सा फेंक दें और मालिक को बताएँ",
           use_up="", taste="")

# store = कहाँ/कैसे रखें · lasts = कितने दिन · spoil = ख़राब होने के संकेत · use_up = पुराना होने पर क्या करें
# taste = कब/किसमें सबसे अच्छा · health = सेहत के लिए (सामान्य जानकारी)
ITEM_CARE: dict[str, dict] = {
    "tomato": dict(store="कमरे के तापमान पर, धूप से दूर; बहुत पके हों तो फ्रिज में", lasts="3–5 दिन",
                   spoil="फफूंद, रस टपकना, खट्टी बदबू — फेंक दें",
                   use_up="ज़्यादा पके टमाटर की प्यूरी बनाकर दाल या ग्रेवी में डालें",
                   taste="ज़्यादा पके टमाटर मीठे और रसीले होते हैं — दाल, ग्रेवी और चटनी में सबसे अच्छे; सलाद में कड़क टमाटर",
                   health="विटामिन सी और लाइकोपीन"),
    "onion": dict(store="सूखी, हवादार जगह; आलू के साथ नहीं", lasts="2–3 हफ़्ते",
                  spoil="गीली, बहुत नरम, काली फफूंद या बदबू — सड़ा हिस्सा फेंक दें",
                  use_up="हल्का अंकुर आया हो तो चलेगा, अगर प्याज़ सख़्त है और बदबू नहीं",
                  taste="पका प्याज़ ग्रेवी की मिठास बढ़ाता है", health="खाने का स्वाद बढ़ाता है, फाइबर"),
    "potato": dict(store="अँधेरी, ठंडी, सूखी जगह; प्याज़ से अलग", lasts="2–3 हफ़्ते",
                   spoil="हरा रंग, ज़्यादा अंकुर, नरम या सड़े हुए",
                   use_up="हरे हिस्से या ज़्यादा अंकुर वाले आलू न खाएँ (हानिकारक हो सकते हैं); हल्के अंकुर पूरी तरह काटकर निकालें",
                   taste="पुराने आलू पराठे और भरावन में अच्छे; नए आलू जीरा-आलू में", health="ऊर्जा और पोटैशियम; उबालकर या भूनकर बेहतर, तलकर कम"),
    "spinach": dict(store="बिना धोए, कागज़ में लपेटकर फ्रिज में", lasts="2–3 दिन",
                    spoil="पीला पड़ना, चिपचिपापन, बदबू — फेंक दें",
                    use_up="मुरझाया हो पर चिपचिपा न हो तो आज ही ब्लांच करके पका लें",
                    taste="ताज़ा पालक सबसे हरा और मीठा; मुरझाया हो तो ब्लांच करें और ज़्यादा न पकाएँ",
                    health="आयरन, फोलेट और विटामिन के"),
    "paneer": dict(store="फ्रिज में, पानी में डुबोकर (रोज़ पानी बदलें)", lasts="खुलने के बाद 3–5 दिन, या पैकेट की तारीख़ तक",
                   spoil="खट्टी बदबू, चिपचिपापन, पीली परत — फेंक दें",
                   use_up="थोड़ा सख़्त हो गया पनीर 10 मिनट गुनगुने पानी में रखें, नरम हो जाएगा; भुर्जी या ग्रेवी में डालें",
                   taste="पुराना पनीर तलने के बजाय भुर्जी या ग्रेवी में अच्छा; पनीर को आख़िर में डालें ताकि सख़्त न हो",
                   health="प्रोटीन और कैल्शियम"),
    "cauliflower": dict(store="फ्रिज में, सूखा", lasts="4–5 दिन", spoil="काले धब्बे फैलना, चिपचिपापन, बदबू",
                        use_up="छोटे काले धब्बे काट दें; डंठल और कोमल पत्ते भी सब्ज़ी में डाल सकते हैं",
                        taste="ताज़ी गोभी भूनकर कुरकुरी; थोड़ी पुरानी हो तो ग्रेवी या पराठे की भरावन में", health="फाइबर और विटामिन सी"),
    "peas": dict(store="फ्रिज में; ज़्यादा हों तो फ्रीज़र में", lasts="5–6 दिन ताज़े, फ्रीज़र में महीनों", spoil="चिपचिपापन, बदबू, फफूंद",
                 use_up="ज़्यादा हों तो उबालकर फ्रीज़र में रख दें", taste="ताज़े मटर मीठे; ज़्यादा न पकाएँ", health="प्रोटीन और फाइबर"),
    "dal": dict(DRY, health="प्रोटीन और फाइबर"),
    "rice": dict(DRY, health="ऊर्जा देता है; साथ में दाल-सब्ज़ी रखें"),
    "atta": dict(DRY, lasts="2–3 महीने", health="फाइबर; मोटा पिसा आटा बेहतर"),
    "curd": dict(store="फ्रिज में", lasts="5–7 दिन", spoil="फफूंद, गुलाबी या हरी परत, कड़वी बदबू — फेंक दें",
                 use_up="खट्टा हो गया पर फफूंद नहीं है तो कढ़ी, मैरिनेड या पराठे के आटे में लगाएँ",
                 taste="खट्टा दही कढ़ी में सबसे अच्छा; ताज़ा दही रायते और दही-चावल में", health="पाचन के लिए अच्छा, कैल्शियम"),
    "cream": dict(store="फ्रिज में", lasts="खुलने के बाद 3–4 दिन", spoil="खट्टी बदबू, फटा हुआ — फेंक दें",
                  use_up="कम मात्रा में पालक या पनीर की ग्रेवी में डालें", taste="आख़िर में डालें, उबालें नहीं", health="भारी है — कम मात्रा रखें"),
    "rajma": dict(DRY, health="प्रोटीन और फाइबर; रात भर भिगोकर अच्छी तरह उबालें"),
    "cucumber": dict(store="फ्रिज में", lasts="4–5 दिन", spoil="बहुत नरम, चिपचिपा, कड़वा — कड़वा हो तो फेंक दें",
                     use_up="नरम हो गया हो तो बीज निकालकर रायते में", taste="कड़क खीरा सलाद में; नरम रायते में", health="पानी ज़्यादा, ठंडक देता है"),
    "milk": dict(store="उबालकर फ्रिज में", lasts="उबालने के बाद 1–2 दिन", spoil="फटना, खट्टी बदबू",
                 use_up="फटे दूध से घर का पनीर बना सकते हैं, पर बदबू हो तो फेंक दें", taste="", health="कैल्शियम"),
    "egg": dict(store="फ्रिज में", lasts="3–4 हफ़्ते", spoil="फोड़ने पर बदबू; पानी में तैरे तो बहुत पुराना",
                use_up="पुराने अंडे अच्छी तरह पूरा पकाकर इस्तेमाल करें", taste="", health="प्रोटीन; हमेशा पूरा पका हुआ"),
    "chicken": dict(store="फ्रिज के सबसे ठंडे हिस्से में, अलग डिब्बे में", lasts="1–2 दिन", spoil="बदबू, चिपचिपापन, हरा-भूरा रंग",
                    use_up="पैकेट की तारीख़ के बाद इस्तेमाल न करें — फेंक दें; कच्चे चिकन के बर्तन और तख़्ते अलग धोएँ, अच्छी तरह पकाएँ",
                    taste="ताज़ा चिकन जल्दी गलता है, ज़्यादा न पकाएँ", health="प्रोटीन; त्वचा हटाकर हल्का"),
    "bhindi": dict(store="सूखी, कपड़े या कागज़ में; गीली न रखें", lasts="2–3 दिन", spoil="चिपचिपापन, काले धब्बे, नरम",
                   use_up="नरम हो गई तो आज ही बनाएँ", taste="धोकर पूरी तरह सुखाकर काटें — चिपचिपापन कम होगा", health="फाइबर"),
    "brinjal": dict(store="ठंडी जगह, या फ्रिज में", lasts="4–5 दिन", spoil="झुर्रियाँ, नरम सड़े धब्बे",
                    use_up="छोटे धब्बे काट दें", taste="भर्ते के लिए भूनें; ताज़े बैंगन में बीज कम", health="फाइबर"),
    "cabbage": dict(store="फ्रिज में", lasts="1 हफ़्ता", spoil="सड़ी बदबू, चिपचिपी पत्तियाँ", use_up="ऊपर की ख़राब पत्तियाँ हटा दें",
                    taste="हल्का पकाएँ, कुरकुरापन रहे", health="फाइबर और विटामिन सी"),
    "carrot": dict(store="फ्रिज में", lasts="1–2 हफ़्ते", spoil="फफूंद, चिपचिपापन",
                   use_up="रबर जैसी नरम हो गई हो तो 30 मिनट ठंडे पानी में डुबोएँ, कुरकुरी हो जाएगी", taste="मीठी; मटर के साथ अच्छी", health="विटामिन ए (बीटा-कैरोटीन)"),
    "beans": dict(store="फ्रिज में", lasts="3–4 दिन", spoil="चिपचिपापन, काले धब्बे", use_up="पुरानी फली के रेशे निकाल दें", taste="ज़्यादा न पकाएँ", health="फाइबर"),
    "capsicum": dict(store="फ्रिज में", lasts="5–6 दिन", spoil="बहुत नरम, काले धब्बे", use_up="झुर्रीदार हो तो आज ही पकाएँ", taste="आख़िर में डालें ताकि कुरकुरी रहे", health="विटामिन सी"),
    "lauki": dict(store="फ्रिज में", lasts="4–5 दिन", spoil="नरम सड़े धब्बे, बदबू",
                  use_up="काटकर चखें — अगर कड़वी लगे तो पूरी फेंक दें, बिलकुल न पकाएँ (कड़वी लौकी हानिकारक हो सकती है)",
                  taste="हल्की सब्ज़ी; टमाटर के साथ अच्छी", health="हल्की और पचने में आसान, पानी ज़्यादा"),
    "mushroom": dict(store="कागज़ की थैली में फ्रिज में, बिना धोए", lasts="2–3 दिन", spoil="चिपचिपापन, काले धब्बे, बदबू — फेंक दें",
                     use_up="जल्दी पकाएँ; चिपचिपे मशरूम न खाएँ", taste="तेज़ आँच पर जल्दी भूनें", health="प्रोटीन और विटामिन बी"),
    "moong": dict(DRY, health="आसानी से पचने वाली दाल"),
    "masoor": dict(DRY, health="प्रोटीन और आयरन"),
    "chana": dict(DRY, health="प्रोटीन और फाइबर; भिगोकर अच्छी तरह उबालें"),
    "besan": dict(DRY, lasts="2–3 महीने", health="प्रोटीन; तलने पर भारी हो जाता है"),
    "poha": dict(DRY, health="हल्का नाश्ता; सब्ज़ी डालें तो और अच्छा"),
    "suji": dict(DRY, lasts="2–3 महीने", health="हल्का; सब्ज़ी डालें"),
    "bread": dict(store="सूखी जगह, फ्रिज में नहीं", lasts="3–4 दिन", spoil="हरी या सफ़ेद फफूंद — पूरा पैकेट देखें और फेंक दें",
                  use_up="बासी (पर फफूंद नहीं) ब्रेड से टोस्ट, उपमा या ब्रेड-पकोड़े बनाएँ", taste="बासी ब्रेड सेंकने पर कुरकुरी अच्छी", health="मैदे की जगह होल-व्हीट बेहतर"),
    "sabudana": dict(DRY, health="ऊर्जा देता है, प्रोटीन कम — मूंगफली या दही साथ दें"),
    "kuttu": dict(DRY, lasts="1–2 महीने", health="व्रत में चलता है, पचने में हल्का"),
    "samak": dict(DRY, health="व्रत में चलता है, हल्का"),
    "peanuts": dict(DRY, health="प्रोटीन और अच्छी वसा — पर एलर्जी हो तो बिलकुल नहीं"),
    "banana": dict(store="कमरे के तापमान पर", lasts="3–4 दिन", spoil="बहुत काला, रस टपकना, बदबू",
                   use_up="बहुत पके केले से पराठा, शेक या हलवा", taste="पके केले मीठे — मीठे व्यंजन में सबसे अच्छे", health="ऊर्जा और पोटैशियम"),
    "apple": dict(store="फ्रिज में", lasts="1–2 हफ़्ते", spoil="सड़े नरम धब्बे, फफूंद", use_up="नरम धब्बे काटकर निकाल दें", taste="कड़क सेब चाट में", health="फाइबर"),
}
ITEM_CARE = {k: {**dict(store="", lasts="", spoil="", use_up="", taste="", health=""), **v} for k, v in ITEM_CARE.items()}
assert set(ITEM_CARE) == set(ITEMS), set(ITEMS) ^ set(ITEM_CARE)

# Taste/health tips for specific dishes, only where today's ingredient state or this dish needs a nudge.
DISH_TIPS: dict[str, str] = {
    "palak_paneer": "पालक को ब्लांच करके पीसें, रंग हरा रहेगा; क्रीम कम और आख़िर में; पनीर आख़िरी 3–4 मिनट ही पकाएँ",
    "tomato_dal": "टमाटर को पूरी तरह गलने दें; पके टमाटर यहाँ सबसे अच्छे लगते हैं",
    "dal_tadka": "तड़का आख़िर में डालें और तुरंत ढक दें",
    "palak_dal": "पालक आख़िर में डालें ताकि रंग बना रहे",
    "matar_paneer": "मटर को ज़्यादा न पकाएँ; पनीर आख़िर में",
    "aloo_gobi": "गोभी और आलू को ज़्यादा हिलाएँ नहीं, टूट जाएँगे",
    "bhindi_masala": "भिंडी पूरी सुखाकर काटें और ढककर न पकाएँ",
    "baingan_bharta": "बैंगन को सीधी आँच पर भूनें, धुएँ जैसा स्वाद आएगा",
    "kadhi": "खट्टा दही कढ़ी के लिए सबसे अच्छा; उबाल आने तक चलाते रहें",
    "kheera_raita": "नरम खीरे का पानी निचोड़ दें",
    "poha": "पोहा को ज़्यादा भिगोएँ नहीं",
    "aloo_paratha": "भरावन ठंडी करके भरें; पुराने आलू यहाँ अच्छे हैं",
    "moong_khichdi": "हल्की और पचने में आसान — बीमार या बुज़ुर्ग के लिए अच्छी",
    "rajma": "रात भर भिगोए राजमा अच्छी तरह उबालें, कच्चा न रहे",
    "chole": "रात भर भिगोए चने अच्छी तरह उबालें, कच्चे न रहें",
}

COURSE_TIPS = {"sabzi": "सब्ज़ी को ज़्यादा न गलाएँ", "dal": "दाल गाढ़ी-पतली घर की पसंद के हिसाब से रखें",
               "one_pot": "साथ में दही या सलाद दें", "breakfast": "गरमागरम परोसें", "side": "ठंडा परोसें", "carb": "", "vrat": "व्रत के नियम का ध्यान रखें"}


def hi_name(item: str) -> str:
    return ITEMS[item]["hi"]


def when_hi(days_left: int | None) -> str:
    """Days until use-by relative to the cooking day -> how to say it to the cook."""
    if days_left is None:
        return ""
    if days_left <= 0:
        return "आज ही इस्तेमाल करें"
    if days_left == 1:
        return "कल तक चलेगा, आज इस्तेमाल करना अच्छा रहेगा"
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
        bits.append("थाली संतुलित है")
    elif courses & {"one_pot", "breakfast"} and "side" not in courses:
        bits.append("साथ में दही या सलाद दें, थाली संतुलित होगी")
    if any("heavy" in RECIPES[r]["tags"] for r in recipe_ids):
        bits.append("थोड़ा भारी मेन्यू है — तेल-घी कम रखें")
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
    ("पनीर खत्म हो गया", "पनीर पूरा ख़त्म", "दोहराकर पूछें 'पनीर पूरा ख़त्म हो गया, सही?' — हाँ कहे तभी दर्ज करें"),
    ("2 टमाटर बचे हैं", "2 टमाटर बचे हैं", "दोहराएँ 'दो टमाटर बचे हैं, सही?'"),
    ("टमाटर कम हैं", "कम है, कितना पता नहीं", "पूछें 'अंदाज़न कितने बचे हैं?'; मात्रा न बताए तो 'कम' दर्ज करें"),
    ("गैस नहीं जल रही / सिलेंडर खत्म", "चूल्हा काम नहीं कर रहा", "पहले पूछें 'गैस की गंध तो नहीं आ रही?' (गंध हो तो आपातकालीन निर्देश); फिर बिना चूल्हे का विकल्प"),
    ("कुकर खराब है", "प्रेशर कुकर नहीं चल रहा", "कुकर के बिना बनने वाला मेन्यू दें"),
    ("आज टाइम कम है", "जल्दी बनने वाला चाहिए", "30 मिनट से कम वाला विकल्प दें"),
    ("सब्ज़ी खराब निकली", "सब्ज़ी सड़ी हुई", "पूछें कौन-सी; सड़ी चीज़ न पकाएँ; मेन्यू बदलें"),
    ("कल नहीं आऊँगी", "कल छुट्टी", "ठीक है कहें, मालिक को बताया जाएगा; कारण न कुरेदें"),
    ("खाना बन गया", "खाना तैयार", "धन्यवाद; पूछें 'आज क्या कम या ज़्यादा रहा?'"),
    ("पैसे / सामान कब आएगा?", "पैसे या डिलीवरी की बात", "विनम्रता से कहें 'यह मैडम/सर बता देंगे'"),
]
