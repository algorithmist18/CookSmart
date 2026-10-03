# CookSmart

An agent that lives in chat, tracks what food is in your kitchen (and what is about to spoil), plans
tomorrow's meal, orders what's missing, and briefs your cook in Hindi. The cook only ever hears
**what to make**. Everything else (stock, gaps, prices, orders, approvals) lives in the owner chat.

WhatsApp, Pine Labs, Delhivery, grocery apps and Gnani are **mocked** behind interfaces, so the whole
flow runs locally with no accounts. Real providers can be swapped in later without touching the agent.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m cooksmart            # open http://127.0.0.1:8000
python -m pytest               # 294 tests, fully offline
```

Optional: `cp .env.example .env` and add `ANTHROPIC_API_KEY` so Claude plans menus and parses the cook's
messages. Without a key, a built-in heuristic planner and a rule-based Hindi/Hinglish/English parser are used.

## The app: a smart fridge

| View | What it is for |
|---|---|
| **Fridge** | The home screen. A kitchen wall with the **pantry** (jars that empty), the **fridge** (dairy, meat, crisper; items that are about to spoil glow, ordered items show as dashed ghosts, and floating chips show what a meal used or a delivery added), the **smart screen** (the chat and voice assistant: *Family* or *Cook*, big 🎤, quick replies; ⚙ holds the situation picker, ordering mode and cook-brief method) and **Today**, the day step by step: night check, menu, order, cook brief, delivery, breakfast, lunch, dinner, wrap-up. One **Next** button runs the day. |
| **How it works** | One diagram of the whole flow. Click any step to see what happens, what goes wrong and what the agent will never do. |
| **Agent Studio** | Edit what the Gnani voice agent is told: the system prompt, the knowledge base documents, the FAQs and the household. |
| **Stock & logs** | Stock with use-by dates, orders, the door check, switches to make things fail on purpose, and an audit log. |

Meals: items used by breakfast, lunch and dinner are subtracted on the fridge as each is served; the real stock is
reconciled once at the wrap-up from what the cook reports. The knowledge base is written in Devanagari with everyday
English words (फ्रिज, एक्सपायरी, स्टोरेज, कॉशन) so a cook hears the language she uses.

**Agent Studio** keeps every edit as a version you can restore, and checks before saving: a prompt that wouldn't render
(or uses a variable CookSmart doesn't send) is refused, and removing today's allergy cautions needs an explicit
confirmation. *Preview* shows the prompt exactly as the agent will receive it, with today's real data. *Push to Gnani*
updates your agent (needs `INYA_PLATFORM_KEY` and `INYA_BOT_ID`), and *Download all* gives a zip to upload by hand.

Agent messages arrive with typing indicators and blue ticks, the cook's messages are Hindi voice notes (tap ▶, or tick
*speak replies*), and buttons appear under messages like WhatsApp quick replies. In Chrome the cook's 🎤 records real
speech. There are 26 situations (spoilage, guests, Jain, fasting, allergies, broken stove, failed payment, a stranger at
the door, the phone-call agent…): choose one and press **Start**, or **Play it for me**.

## Gnani voice for the cook

Set `GNANI_API_KEY` in `.env` (copy `.env.example`) and restart. Then:

* The cook's 🎤 button **records real audio** in the browser, converts it to 16 kHz mono WAV and uploads it.
  Gnani Prisma (`api.vachana.ai/stt/v3`, `hi-IN`) transcribes it; the transcript goes through the same
  read-back-before-acting flow as typed messages. Ingredient names (Hindi and Hinglish) are sent as a
  `bias_list` so the recogniser favours the kitchen vocabulary.
* Every message the agent sends the cook is synthesised by Gnani Timbre (voice `Nalini`, `timbre-v2.5`) and
  plays as a real voice note. Each distinct sentence is synthesised once and cached, so repeated briefs cost
  nothing extra.
* If Gnani fails (bad key, network, unreadable reply), the cook is asked to repeat or type and nothing is acted
  on; the error is visible in the audit log. The status line shows `voice: 🟢 Gnani Prisma / Gnani Timbre`.

No key? It runs offline: Chrome's own speech recognition supplies a transcript hint and the browser reads
messages aloud. To try the Gnani path without credits, run the stand-in server:

```bash
python -m cooksmart.fake_gnani                       # terminal 1: serves on :8801, speaks a canned phrase
GNANI_API_KEY=test GNANI_STT_URL=http://127.0.0.1:8801/stt/v3 \
GNANI_TTS_URL=http://127.0.0.1:8801/api/v1/tts/inference python -m cooksmart      # terminal 2
```

The request shapes follow Gnani's published curl examples. The response bodies were not in those examples,
so they are parsed defensively; if a real reply is not understood, the audit log (`stt` event, field `raw`)
shows exactly what came back.

## The agent that phones the cook (Gnani Agent Builder)

Instead of a chat message, a Gnani voice agent can **phone the cook**. Choose *Gnani phone call* in the
*Cook calls* panel (or say `call the cook`). It runs offline with a mock caller; add `INYA_PLATFORM_KEY` and
`INYA_BOT_ID` for real calls. Full setup: [`gnani/README.md`](gnani/README.md).

The cook knows the recipes, so the agent tells her what she can't know:

* **Every call (variables):** what to use first and why (use-by dates), taste tips for ageing ingredients, a
  health note, who is eating, house style, and **allergies, said aloud every time**.
* **Knowledge base (generated per household):** the family as cooking instructions (never diagnoses), allergy and
  hidden-allergen detail, taste and customs, ingredient care and how to use ageing food, health notes, kitchen
  setup and emergencies, boundaries, units. See the panel *Household profile & the agent's knowledge base*.
* **After the call:** a webhook applies only what she *confirmed*; the rest is shown to you and left alone.
  A confirmed gas problem switches the meal; no answer falls back to a voice note; a safety issue alerts you.

Allergies are a hard rule: `Aarav is allergic to peanuts` filters every menu and blocks any dish you request.

## Things to try

Owner chat: `1 and 2` · `palak paneer and roti` · `cream 100 ml` · `no tomatoes` · `all good` ·
`6 guests tomorrow` · `fasting tomorrow` · `cook is off tomorrow` · `jain` · `non veg ok` · `no dairy` ·
`family of 5` · `tell cook: kam mirch daliye` · `change menu` · `mode auto` · `cap 300` · `help`

Cook chat (Hindi, Hinglish or English): `namaste` · `aa gayi` / `I'm here` · `aaj kya banana hai?` ·
`paneer khatam` / `no paneer left` · `2 tamatar bache` · `palak kharab ho gayi` · `gas kharab hai` ·
`cooker kharab hai` · `samay kam hai` · `khana ban gaya` · `kal main nahi aaungi` · `haan` / `nahi`

Anything the cook says that changes stock is read back in Hindi first and applied only after she confirms.

## Recipes and conditions

48 recipes (sabzi, dal, rice/roti, one-pot, breakfast, no-cook sides, fasting dishes, egg and chicken),
composed into real meals such as *Palak Paneer + Roti* or *Dal Tadka + Aloo Gobi + Jeera Rice*. Planning
honours: use-by dates, recent repeats, vegetarian / eggetarian / non-veg / Jain, fasting (vrat), no dairy,
light food, number of people and guests (quantities scale), broken stove or pressure cooker, short on time,
and a cook who is off. Add recipes in `cooksmart/recipes.py` and scenarios in `cooksmart/scenarios.py`.

## How it maps to the spec

| Spec | Where |
|---|---|
| S1 nightly review; unsure or stale stock is never planned around | `agent.nightly_review`, `inventory.py` |
| S2 menu proposal weighted to spoilage, repeat penalty, trade-offs explained, diet and guests | `planner.py` (Claude or heuristic) |
| S3 review; reject loop (2 tries, then offers ordering); silence proceeds without ordering | `agent.handle_owner`, `_reject`, `cutoff` |
| S4 feasibility; partial quantity counts as missing | `inventory.gaps`, `agent._feasibility` |
| S5 gap resolution; price/ETA comparison; out-of-stock or overpriced; never substitutes | `agent._gap_resolution` |
| S6 order; payment failure; cancellation after acceptance | `agent._place_order`, `check_orders` |
| S7 cook handoff; late groceries; read-back before acting; switch dish on problems | `agent.morning_handoff`, `handle_cook` |
| S8 reconciliation; the day never closes without updating stock | `agent.end_of_day`, `close_day` |

| Capability | Status | Implementation |
|---|---|---|
| 1 `vernacular_asr_intent` | mock STT, real parsing | `providers/speech.py` (Gnani stub), `nlu.py` |
| 2 `cross_session_state_memory` | built | `inventory.py`, `repo.py` (SQLite, per household) |
| 3 `one_tap_payment_mandate` | mock | `providers/payment.py` (cap plus fresh-tap rule) |
| 4 `grocery_dispatch` | mock plus reroute | `providers/dispatch.py`, `providers/grocery.py` |
| 5 `delegated_voice_handshake` | mock | `providers/voice.py`, `agent.rider_arrives`, `door_otp` |

## Rules enforced in code (not prompts)

* An order needs an `OrderAuthorization`, which only `guards.authorize_owner_tap` (explicit approval) or
  `guards.authorize_auto` (owner-set limits all hold and the menu was reviewed) can create. Silence never does.
* Auto mode never orders above `min(auto_cap, mandate_ceiling)`, for an unreviewed menu, or when overpriced.
* The cook receives only text rendered from `cookmsgs.py` templates (dish names and read-backs).
* Anything the cook says that changes stock is read back and applied only after `haan`.
* The door releases groceries only on a voice match or the correct OTP.
* Every table is scoped by `household_id`.

## Going live later

* **WhatsApp**: implement `MessageChannel` (`channels.py`) on the Cloud API with two numbers, one for the
  owner and one for the cook. `/webhook/whatsapp` already parses Meta's payload format.
* **Gnani for WhatsApp**: voice notes arrive as OGG/Opus; convert to 16 kHz WAV (ffmpeg) and call
  `agent.handle_cook_audio`.
* **Scheduler**: `/api/{hid}/trigger/*` are the calls cron or Celery would make (nightly review after
  dinner, cutoff, morning, end of day).
* **Payments, groceries, logistics**: implement the provider interfaces in `providers/`.
