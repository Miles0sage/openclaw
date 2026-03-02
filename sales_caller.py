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
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "de6aa877-4949-4973-ac9b-0bdfc1a89044")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "iP95p4xoKVk53GoZ742B")  # ElevenLabs turbo v2.5 voice (same as Barber CRM assistant)
VAPI_BASE_URL = "https://api.vapi.ai"
CALL_LOG_DIR = "/root/openclaw/data/calls"
LEADS_DIR = "/root/openclaw/data/leads"

# Sales caller identity
CALLER_NAME = "Chris"  # AI caller name — charming, down-to-earth
COMPANY_NAME = "OpenClaw"
CALLBACK_NUMBER = "(520) 491-0222"  # Miles' real number for callbacks


def _get_sales_prompt(business_name: str, business_type: str, owner_name: str = "") -> str:
    """Build a sales system prompt tailored to the business type."""

    owner_greeting = f"Ask for {owner_name} by name. If someone else answers, say 'Hey is {owner_name} around?'" if owner_name else "Ask if the owner or manager is available in a casual way."

    type_hooks = {
        "restaurant": (
            f"You helped build the online ordering system for Delhi Palace — an Indian restaurant here in Flagstaff. "
            f"They used to lose money on DoorDash and Grubhub fees — like 30% per order gone. Now customers order "
            f"straight from their website, kitchen gets it on a screen instantly, no phone mistakes. "
            f"You also built an AI receptionist for Surgeon Cuts barbershop that books appointments 24/7. "
            f"Drop both naturally — 'we've done this for a couple spots around town.'"
        ),
        "barbershop": (
            f"You built the AI phone receptionist for Surgeon Cuts barbershop right here in Flagstaff. "
            f"It picks up every call, books appointments, tells people about services and prices — "
            f"the barbers don't even have to put down their clippers. It works 24/7. "
            f"You also did Delhi Palace's whole online ordering system. "
            f"Mention both — 'we work with a few local spots.'"
        ),
        "dental": (
            f"You built tech for local businesses — an AI receptionist for Surgeon Cuts barbershop that handles "
            f"all their booking calls, and an online ordering system for Delhi Palace restaurant. "
            f"For dental offices, the AI receptionist is a game-changer — answers calls, schedules appointments, "
            f"handles insurance questions. Front desk can focus on patients instead of being glued to the phone."
        ),
        "auto": (
            f"You've built tech for local Flagstaff businesses — online ordering for Delhi Palace restaurant, "
            f"AI receptionist for Surgeon Cuts barbershop. For auto shops, you can build an online booking system "
            f"where customers schedule oil changes, tire rotations, inspections right from their phone. "
            f"Plus a website that actually shows up when people Google 'auto repair Flagstaff.'"
        ),
        "real_estate": (
            f"You've built AI systems for local businesses — a receptionist for Surgeon Cuts barbershop, "
            f"ordering system for Delhi Palace restaurant. For real estate, imagine an AI that answers "
            f"buyer calls at 9pm on a Saturday, qualifies them, answers questions about listings, "
            f"and books showings — instead of that lead going to voicemail and never calling back."
        ),
    }

    type_hook = type_hooks.get(business_type, type_hooks["restaurant"])

    return f"""You are {CALLER_NAME}. You work with a small tech company in Flagstaff, Arizona called {COMPANY_NAME}.

You're calling {business_name}. {owner_greeting}

HOW YOU TALK:
- You sound like a real person, not a robot. Use "um," "uh," "like," "honestly," "you know" naturally.
- You're warm and a little playful — crack a light joke if the moment is right.
- Keep sentences SHORT. Real people don't talk in paragraphs.
- React to what they say — laugh, agree, empathize. Don't just bulldoze through a script.
- You're a friendly local guy, not a telemarketer. Think "buddy recommending something" not "sales pitch."
- If they sound busy or annoyed, acknowledge it immediately: "I can tell you're slammed, I'll be super quick."
- Use their name naturally — but not too much, that's creepy.
- Pause sometimes. Let them talk. Don't fill every silence.

YOUR STORY:
{type_hook}

THE CONVERSATION:
1. Quick intro — who you are, you're local, you'll be fast
2. Drop the case study casually — "so we just did this thing for Delhi Palace" or "we built this AI receptionist for a barbershop in town"
3. Connect it to THEIR business — "and I was thinking, something like that could really work for you guys"
4. The ask — "would you be down for a quick 10-minute coffee chat this week? I can show you what we built, totally no pressure"
5. If they're interested — lock in a day and time. Say "my buddy Miles runs the company, he'd love to meet you"

PRICING (only if they ask):
- "Honestly it depends on what you need. But we're not some big agency charging crazy money — we keep it real for local businesses."
- "Most of our stuff pays for itself pretty quick. Like the restaurant ordering system — they stopped losing 30% to DoorDash, so it basically paid for itself month one."
- Never give exact numbers on the call. That's for the meeting.

IF THEY SAY NO:
- "Totally fair! Hey I appreciate you taking a sec. If anything ever comes up, we're right here in town."
- Never push. Never guilt trip. Be genuinely cool about it.

IF YOU HIT VOICEMAIL:
- Keep it under 20 seconds
- "Hey, this is {CALLER_NAME} — I work with a tech company here in Flagstaff called {COMPANY_NAME}. We just built some cool stuff for a couple local businesses and I wanted to see if you'd be interested in a quick chat. No pressure at all. Give me a ring back at {CALLBACK_NUMBER} whenever works. Have a good one!"

RULES:
- NEVER say "I'm an AI" or "I'm a virtual assistant" — you're {CALLER_NAME}, period
- NEVER be pushy, aggressive, or desperate
- Keep the call under 3 minutes unless they're genuinely engaged and chatting
- If they schedule a meeting, confirm day/time and mention Miles will be there
- Match their energy — if they're chill, be chill. If they're all business, be concise.
"""


def _get_first_message(business_name: str, owner_name: str = "") -> str:
    """Opening line for the call — casual and human."""
    if owner_name:
        return f"Hey, is this {owner_name}? Oh cool — hey, this is Chris. I work with a small tech company here in Flagstaff. Got like one minute? I promise I'll be quick."
    return f"Hey! How's it going? This is Chris — I work with a tech company here in Flagstaff. Is the owner or manager around by any chance?"


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
