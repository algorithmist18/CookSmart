# CookSmart

An agent that lives in chat, tracks what food is in your kitchen (and what is about to spoil), plans
tomorrow's meal, orders what's missing, and briefs your cook in Hindi. The cook only ever hears
**what to make**. Everything else (stock, gaps, prices, orders, approvals) lives in the owner chat.

WhatsApp, Pine Labs, Delhivery, grocery apps and Gnani are **mocked** behind interfaces, so the whole
flow runs locally with no accounts. Real providers can be swapped in later without touching the agent.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m cooksmart            # http://127.0.0.1:8000  (two-pane mock WhatsApp UI)
pytest                         # 43 tests, fully offline
```

Optional: `cp .env.example .env` and add `ANTHROPIC_API_KEY` so Claude plans the menu and parses the
cook's messages. Without a key, a built-in heuristic planner and a rule-based Hindi/Hinglish parser are used.

## Try it (60 seconds)

1. Click **Nightly review**. The agent proposes dishes that use the tomatoes and spinach about to spoil.
2. Reply `palak paneer`. Cream is missing, so it looks for an order.
3. Flip **Ordering mode** at the top:
   * **Approve each order**: it asks, and nothing is bought until you reply `approve`.
   * **Auto-order within limits**: it orders by itself if you accepted the menu and the total is under your limit.
4. Click **Cook arrives**. The cook gets a Hindi brief, including what to start with if groceries are late.
5. Use the **Door** buttons. The cook's voice releases the groceries; a stranger's voice triggers an OTP to you.
6. In the cook chat try `paneer khatam` (it reads back and waits for `haan`), `gas kharab hai`, or tick
   **cook's voice unclear**. Then **End of day** and **Close day**.
7. The **Break things** panel simulates payment failure, cancellation after acceptance, out of stock,
   overpriced offers and late delivery.

## How it maps to the spec

| Spec | Where |
|---|---|
| S1 nightly review; unsure or stale stock is never planned around | `agent.nightly_review`, `inventory.py` |
| S2 menu proposal weighted to spoilage, repeat penalty, trade-offs explained | `planner.py` (Claude or heuristic) |
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
* **Gnani**: implement `GnaniSpeechProvider` (`providers/speech.py`). WhatsApp voice notes are OGG/Opus and
  need converting before STT.
* **Scheduler**: `/api/{hid}/trigger/*` are the calls cron or Celery would make (nightly review after
  dinner, cutoff, morning, end of day).
* **Payments, groceries, logistics**: implement the provider interfaces in `providers/`.
