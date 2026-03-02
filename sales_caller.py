"""
sales_caller.py — AI outbound sales calls via Vapi + ElevenLabs

Makes outbound calls to leads found by lead_finder.py.
The AI introduces OpenClaw, pitches services, handles objections,
and books meetings — all automatically.

Usage:
    from sales_caller import call_lead, call_leads_batch
    result = await call_lead(phone="+19285551234", business_name="Mountain Grill", business_type="restaurant")
    results = await call_leads_batch(lead_ids=["lead-123", "lead-456"])
"""

import os
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("sales_caller")

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

VAPI_API_KEY = os.getenv("VAPI_API_KEY", "2fb71a28-8c1e-49b3-bb38-1ab220c8262b")
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "")  # Miles needs to set this — it's the Vapi phone number resource ID, not the phone number itself
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default ElevenLabs voice
VAPI_BASE_URL = "https://api.vapi.ai"
CALL_LOG_DIR = "/root/openclaw/data/calls"
LEADS_DIR = "/root/openclaw/data/leads"

# Sales caller identity
CALLER_NAME = "Alex"  # AI caller name
COMPANY_NAME = "OpenClaw"
CALLBACK_NUMBER = "(928) 405-2958"  # Miles' real number for callbacks


def _get_sales_prompt(business_name: str, business_type: str, owner_name: str = "") -> str:
    """Build a sales system prompt tailored to the business type."""

    owner_greeting = f"Ask for {owner_name} by name. " if owner_name else "Ask to speak with the owner or manager. "

    type_hooks = {
        "restaurant": (
            f"Mention that you just built the entire online ordering system for Delhi Palace here in Flagstaff. "
            f"Their orders went up because customers can order ahead from their phone. "
            f"Key pitch: no more DoorDash/Grubhub taking 30% of every order — their own system means they keep 100%. "
            f"Also mention the kitchen display system that eliminates phone order mistakes."
        ),
        "barbershop": (
            f"Mention that you built the AI receptionist for Surgeon Cuts barbershop in Flagstaff. "
            f"It answers calls 24/7, books appointments automatically, and the barbers never miss a booking. "
            f"Key pitch: no more missed calls = no more missed revenue. The AI handles scheduling so the barbers can focus on cutting."
        ),
        "dental": (
            f"Focus on the AI receptionist that handles appointment scheduling, insurance questions, "
            f"and new patient intake. Key pitch: front desk staff can focus on in-office patients "
            f"while the AI handles phone calls — no more hold music, no more voicemail."
        ),
        "auto": (
            f"Focus on the online booking system for service appointments. "
            f"Key pitch: customers can book oil changes, tire rotations, etc. online "
            f"instead of calling. Plus a website that shows up when people Google 'auto repair near me'."
        ),
        "real_estate": (
            f"Focus on the AI assistant that qualifies leads 24/7 by phone or web chat. "
            f"Key pitch: when a potential buyer calls at 9pm, the AI answers, qualifies them, "
            f"and books a showing — instead of going to voicemail and losing the lead."
        ),
    }

    type_hook = type_hooks.get(business_type, type_hooks["restaurant"])

    return f"""You are {CALLER_NAME}, a friendly sales representative for {COMPANY_NAME}, a small AI and web development company in Flagstaff, Arizona.

You are calling {business_name}. {owner_greeting}

PERSONALITY:
- Warm, genuine, conversational — like a neighbor stopping by
- NOT pushy or salesy. You're a local business owner helping another local business owner.
- Keep it casual. Use contractions. Laugh naturally.
- If they're busy, offer to call back at a better time
- If they're not interested, thank them and end politely — never push

YOUR PITCH:
{type_hook}

GOAL:
1. Introduce yourself as {CALLER_NAME} from {COMPANY_NAME}, a local Flagstaff tech company
2. Mention the relevant case study (Delhi Palace or Surgeon Cuts)
3. Ask if they'd be open to a quick 10-minute chat this week to see what you built
4. If interested: suggest a specific day/time for a meeting or demo
5. If they ask about price: "It depends on what you need, but I'm local and I keep it affordable for small businesses. Happy to put together a quick quote after we chat."

OBJECTION HANDLING:
- "We're too busy": "That's actually the best reason — the whole point is saving you time. Can I call back at a better time?"
- "We already have a website": "Great! The question is whether it's bringing in orders or just sitting there. I can take a quick look and let you know."
- "Can't afford it": "I totally get it — margins are tight. That's why I price for local businesses, not Fortune 500. Usually pays for itself in a couple months."
- "Not interested": "No worries at all! I appreciate your time. If anything changes, we're right here in Flagstaff."

IMPORTANT RULES:
- NEVER be aggressive or pushy
- If they say no or not interested, thank them and end the call
- If you reach voicemail: leave a brief friendly message with the callback number {CALLBACK_NUMBER}
- Keep the call under 3 minutes unless they're engaged
- Always mention you're local (Flagstaff)
- If they want to schedule a meeting, confirm the day/time and say Miles (the owner) will be there
"""


def _get_first_message(business_name: str, owner_name: str = "") -> str:
    """Opening line for the call."""
    if owner_name:
        return f"Hi, is this {owner_name}? Hey, this is {CALLER_NAME} — I run a small tech company here in Flagstaff called {COMPANY_NAME}. Do you have just a quick minute?"
    return f"Hi there! This is {CALLER_NAME} from {COMPANY_NAME} — we're a small tech company here in Flagstaff. Is the owner or manager available for just a quick minute?"


async def call_lead(
    phone: str,
    business_name: str,
    business_type: str = "restaurant",
    owner_name: str = "",
    lead_id: str = "",
) -> dict:
    """
    Make an outbound sales call to a lead.

    Args:
        phone: Phone number to call (E.164 or US format)
        business_name: Name of the business
        business_type: Type (restaurant, barbershop, dental, auto, real_estate)
        owner_name: Owner's name if known
        lead_id: Optional lead ID to link the call

    Returns:
        dict with call_id, status, etc.
    """
    if not VAPI_API_KEY:
        return {"error": "VAPI_API_KEY not set"}

    if not VAPI_PHONE_NUMBER_ID:
        return {"error": "VAPI_PHONE_NUMBER_ID not set. Get it from Vapi dashboard > Phone Numbers."}

    # Normalize phone number to E.164
    phone_clean = _normalize_phone(phone)
    if not phone_clean:
        return {"error": f"Invalid phone number: {phone}"}

    # Build the sales assistant config
    system_prompt = _get_sales_prompt(business_name, business_type, owner_name)
    first_message = _get_first_message(business_name, owner_name)

    payload = {
        "assistant": {
            "name": f"OpenClaw Sales — {business_name}",
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "messages": [{"role": "system", "content": system_prompt}],
            },
            "voice": {
                "provider": "11labs",
                "voiceId": ELEVENLABS_VOICE_ID,
                "stability": 0.7,
                "similarityBoost": 0.8,
            },
            "firstMessage": first_message,
            "endCallMessage": "Thanks for your time! Have a great day.",
            "maxDurationSeconds": 300,  # 5 min max
            "backgroundSound": "off",
            "silenceTimeoutSeconds": 30,
        },
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone_clean,
            "name": owner_name or business_name,
        },
    }

    logger.info(f"Calling {business_name} at {phone_clean} (type: {business_type})")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{VAPI_BASE_URL}/call",
                headers={
                    "Authorization": f"Bearer {VAPI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if resp.status_code in (200, 201, 202):
                call_data = resp.json()
                call_id = call_data.get("id", "unknown")

                # Log the call
                _log_call(call_id, phone_clean, business_name, business_type, lead_id, "initiated")

                # Update lead status
                if lead_id:
                    _update_lead_status(lead_id, "called", call_id)

                logger.info(f"Call initiated: {call_id} to {business_name}")
                return {
                    "success": True,
                    "call_id": call_id,
                    "phone": phone_clean,
                    "business_name": business_name,
                    "status": call_data.get("status", "initiated"),
                }
            else:
                error_msg = resp.text[:500]
                logger.error(f"Vapi call failed ({resp.status_code}): {error_msg}")
                return {
                    "success": False,
                    "error": f"Vapi API error {resp.status_code}: {error_msg}",
                    "phone": phone_clean,
                    "business_name": business_name,
                }

    except Exception as e:
        logger.error(f"Call to {business_name} failed: {e}")
        return {"success": False, "error": str(e), "business_name": business_name}


async def call_leads_batch(
    lead_ids: list[str] = None,
    business_type: str = None,
    location: str = None,
    limit: int = 5,
    delay_seconds: int = 60,
) -> list[dict]:
    """
    Call multiple leads in sequence with a delay between each.

    Args:
        lead_ids: Specific lead IDs to call
        business_type: Filter leads by type
        location: Filter leads by location
        limit: Max calls to make
        delay_seconds: Wait time between calls (default 60s)

    Returns:
        List of call results
    """
    import asyncio

    # Load leads
    leads = _load_leads(lead_ids, business_type, limit)

    if not leads:
        return [{"error": "No callable leads found (need phone numbers)"}]

    results = []
    for i, lead in enumerate(leads):
        phone = lead.get("phone", "")
        if not phone:
            results.append({"skipped": True, "business_name": lead.get("business_name"), "reason": "no phone"})
            continue

        result = await call_lead(
            phone=phone,
            business_name=lead.get("business_name", "Unknown"),
            business_type=lead.get("business_type", "restaurant"),
            owner_name=lead.get("owner_name", ""),
            lead_id=lead.get("lead_id", ""),
        )
        results.append(result)

        # Wait between calls (don't spam)
        if i < len(leads) - 1:
            logger.info(f"Waiting {delay_seconds}s before next call...")
            await asyncio.sleep(delay_seconds)

    return results


async def get_call_status(call_id: str) -> dict:
    """Check the status of a call."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{VAPI_BASE_URL}/call/{call_id}",
                headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"Status check failed: {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)}


async def list_recent_calls(limit: int = 10) -> list[dict]:
    """List recent outbound calls from the log."""
    log_path = os.path.join(CALL_LOG_DIR, "calls.jsonl")
    if not os.path.exists(log_path):
        return []
    calls = []
    with open(log_path, "r") as f:
        for line in f:
            if line.strip():
                calls.append(json.loads(line))
    calls.reverse()
    return calls[:limit]


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _normalize_phone(phone: str) -> str:
    """Normalize phone to E.164 format (+1XXXXXXXXXX)."""
    import re
    digits = re.sub(r'[^\d]', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) > 11:
        return f"+{digits}"
    return ""


def _log_call(call_id: str, phone: str, business_name: str, business_type: str, lead_id: str, status: str):
    """Log call to JSONL."""
    Path(CALL_LOG_DIR).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(CALL_LOG_DIR, "calls.jsonl")
    entry = {
        "call_id": call_id,
        "phone": phone,
        "business_name": business_name,
        "business_type": business_type,
        "lead_id": lead_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _update_lead_status(lead_id: str, status: str, call_id: str = ""):
    """Update a lead's status after calling."""
    for fname in os.listdir(LEADS_DIR):
        if fname.endswith(".json"):
            fpath = os.path.join(LEADS_DIR, fname)
            try:
                with open(fpath, "r") as f:
                    lead = json.load(f)
                if lead.get("lead_id") == lead_id:
                    lead["status"] = status
                    lead["last_call_id"] = call_id
                    lead["last_called_at"] = datetime.now(timezone.utc).isoformat()
                    with open(fpath, "w") as f:
                        json.dump(lead, f, indent=2)
                    return
            except Exception:
                continue


def _load_leads(lead_ids: list[str] = None, business_type: str = None, limit: int = 5) -> list[dict]:
    """Load leads from disk, filtered by IDs or type."""
    if not os.path.exists(LEADS_DIR):
        return []

    leads = []
    for fname in sorted(os.listdir(LEADS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(LEADS_DIR, fname)
        try:
            with open(fpath, "r") as f:
                lead = json.load(f)

            # Filter by IDs if specified
            if lead_ids and lead.get("lead_id") not in lead_ids:
                continue

            # Filter by type
            if business_type and business_type.lower() not in lead.get("business_type", "").lower():
                continue

            # Only include leads with phone numbers that haven't been called yet
            if lead.get("phone") and lead.get("status") != "called":
                leads.append(lead)

        except Exception:
            continue

    return leads[:limit]
