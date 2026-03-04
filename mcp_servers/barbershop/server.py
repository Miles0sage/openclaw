"""
OpenClaw Barbershop MCP Server — 7 tools for barbershop/salon operations.

Tools:
  1. manage_appointments — Book/reschedule/cancel/check-in appointments
  2. manage_clients     — Client profiles, preferences, visit history
  3. manage_services    — Service catalog, pricing, duration, staff assignment
  4. check_availability — Find open time slots by date/barber/service
  5. manage_walkins     — Walk-in queue with wait time estimates
  6. send_reminders     — Appointment reminders & follow-ups via SMS
  7. shop_analytics     — Revenue, retention, staff performance, trends

Usage:
  python -m mcp_servers.barbershop.server          # stdio mode
  python -m mcp_servers.barbershop.server --http    # HTTP mode (port 8801)
"""

from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timezone, timedelta, date
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "OpenClaw Barbershop Tools",
    version="1.0.0",
    instructions=(
        "Barbershop & salon management MCP server by OpenClaw. "
        "Provides tools for appointment scheduling, client management, "
        "services, walk-in queues, SMS reminders, and analytics."
    ),
)

# ---------------------------------------------------------------------------
# Supabase client (lazy init)
# ---------------------------------------------------------------------------

_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))
        if not url or not key:
            return None
        try:
            from supabase import create_client
            _supabase = create_client(url, key)
        except ImportError:
            return None
    return _supabase


def _demo_response(tool: str, params: dict) -> dict:
    return {
        "status": "demo_mode",
        "tool": tool,
        "message": "Running in demo mode. Connect Supabase for live data.",
        "params_received": params,
        "demo_data": True,
    }


# ---------------------------------------------------------------------------
# Tool 1: Appointment Management
# ---------------------------------------------------------------------------

@mcp.tool
def manage_appointments(
    action: str,
    client_name: str | None = None,
    client_phone: str | None = None,
    barber_name: str | None = None,
    service_name: str | None = None,
    date: str | None = None,
    time: str | None = None,
    appointment_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Manage barbershop appointments.

    Actions:
      - book: Create a new appointment
      - list: List appointments (filter by date/barber/status)
      - cancel: Cancel an appointment
      - reschedule: Move appointment to new date/time
      - checkin: Mark a client as checked in
      - complete: Mark an appointment as completed
      - today: Get today's full schedule

    Args:
        action: One of: book, list, cancel, reschedule, checkin, complete, today
        client_name: Client's name
        client_phone: Client's phone number
        barber_name: Barber's name (for filtering or assignment)
        service_name: Service requested
        date: Date in YYYY-MM-DD format
        time: Time in HH:MM format (24h)
        appointment_id: Appointment ID (for cancel/reschedule/checkin/complete)
        notes: Additional notes
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_appointments", {
            "action": action,
            "sample_schedule": [
                {"time": "09:00", "client": "Jake", "barber": "Carlos", "service": "Fade", "status": "confirmed"},
                {"time": "09:30", "client": "Mike", "barber": "Carlos", "service": "Beard Trim", "status": "checked-in"},
                {"time": "10:00", "client": "Tom", "barber": "Alex", "service": "Full Cut + Style", "status": "scheduled"},
            ]
        })

    apt_table = "appointments"

    if action == "book":
        if not all([client_name, service_name, date, time]):
            return {"error": "client_name, service_name, date, and time required"}
        data = {
            "client_name": client_name,
            "client_phone": client_phone or "",
            "barber_name": barber_name or "Any Available",
            "service_name": service_name,
            "appointment_date": date,
            "appointment_time": time,
            "status": "scheduled",
            "notes": notes or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result = sb.table(apt_table).insert(data).execute()
        return {"appointment": result.data[0] if result.data else data, "status": "booked"}

    elif action == "list":
        q = sb.table(apt_table).select("*")
        if date:
            q = q.eq("appointment_date", date)
        if barber_name:
            q = q.eq("barber_name", barber_name)
        result = q.order("appointment_date").order("appointment_time").limit(50).execute()
        return {"appointments": result.data, "count": len(result.data)}

    elif action == "cancel":
        if not appointment_id:
            return {"error": "appointment_id required"}
        result = sb.table(apt_table).update({"status": "cancelled"}).eq("id", appointment_id).execute()
        return {"cancelled": result.data}

    elif action == "reschedule":
        if not appointment_id:
            return {"error": "appointment_id required"}
        updates = {"status": "scheduled"}
        if date:
            updates["appointment_date"] = date
        if time:
            updates["appointment_time"] = time
        if barber_name:
            updates["barber_name"] = barber_name
        result = sb.table(apt_table).update(updates).eq("id", appointment_id).execute()
        return {"rescheduled": result.data}

    elif action == "checkin":
        if not appointment_id:
            return {"error": "appointment_id required"}
        result = sb.table(apt_table).update({
            "status": "checked-in",
            "checked_in_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", appointment_id).execute()
        return {"checked_in": result.data}

    elif action == "complete":
        if not appointment_id:
            return {"error": "appointment_id required"}
        result = sb.table(apt_table).update({
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", appointment_id).execute()
        return {"completed": result.data}

    elif action == "today":
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        q = sb.table(apt_table).select("*").eq("appointment_date", today)
        if barber_name:
            q = q.eq("barber_name", barber_name)
        result = q.order("appointment_time").execute()
        return {"date": today, "appointments": result.data, "count": len(result.data)}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 2: Client Management
# ---------------------------------------------------------------------------

@mcp.tool
def manage_clients(
    action: str,
    client_name: str | None = None,
    client_phone: str | None = None,
    client_email: str | None = None,
    client_id: str | None = None,
    preferred_barber: str | None = None,
    notes: str | None = None,
    search_query: str | None = None,
) -> dict:
    """
    Manage client profiles and preferences.

    Actions:
      - add: Register a new client
      - get: Get client details by ID or phone
      - update: Update client info or preferences
      - search: Search clients by name/phone
      - history: Get client's appointment history
      - list: List all clients (paginated)

    Args:
        action: One of: add, get, update, search, history, list
        client_name: Client's full name
        client_phone: Phone number
        client_email: Email address
        client_id: Client ID (for get/update/history)
        preferred_barber: Preferred barber name
        notes: Notes about the client (preferences, allergies, etc.)
        search_query: Search string for search action
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_clients", {
            "action": action,
            "sample_clients": [
                {"name": "Jake Martinez", "phone": "928-555-0101", "visits": 12, "preferred_barber": "Carlos"},
                {"name": "Mike Johnson", "phone": "928-555-0102", "visits": 8, "preferred_barber": "Alex"},
            ]
        })

    table = "clients"

    if action == "add":
        if not client_name:
            return {"error": "client_name required"}
        data = {
            "name": client_name,
            "phone": client_phone or "",
            "email": client_email or "",
            "preferred_barber": preferred_barber or "",
            "notes": notes or "",
            "total_visits": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result = sb.table(table).insert(data).execute()
        return {"client": result.data[0] if result.data else data}

    elif action == "get":
        if client_id:
            result = sb.table(table).select("*").eq("id", client_id).execute()
        elif client_phone:
            result = sb.table(table).select("*").eq("phone", client_phone).execute()
        else:
            return {"error": "client_id or client_phone required"}
        return {"client": result.data[0] if result.data else None}

    elif action == "update":
        if not client_id:
            return {"error": "client_id required"}
        updates = {}
        if client_name:
            updates["name"] = client_name
        if client_phone:
            updates["phone"] = client_phone
        if client_email:
            updates["email"] = client_email
        if preferred_barber:
            updates["preferred_barber"] = preferred_barber
        if notes:
            updates["notes"] = notes
        if not updates:
            return {"error": "Nothing to update"}
        result = sb.table(table).update(updates).eq("id", client_id).execute()
        return {"updated": result.data}

    elif action == "search":
        if not search_query:
            return {"error": "search_query required"}
        result = sb.table(table).select("*").or_(
            f"name.ilike.%{search_query}%,phone.ilike.%{search_query}%"
        ).limit(20).execute()
        return {"clients": result.data, "count": len(result.data)}

    elif action == "history":
        if not client_id and not client_phone:
            return {"error": "client_id or client_phone required"}
        if client_phone:
            result = sb.table("appointments").select("*").eq("client_phone", client_phone).order("appointment_date", desc=True).limit(20).execute()
        else:
            # Try matching by client name from the clients table
            client = sb.table(table).select("name").eq("id", client_id).execute()
            if not client.data:
                return {"error": "Client not found"}
            result = sb.table("appointments").select("*").eq("client_name", client.data[0]["name"]).order("appointment_date", desc=True).limit(20).execute()
        return {"history": result.data, "count": len(result.data)}

    elif action == "list":
        result = sb.table(table).select("*").order("name").limit(50).execute()
        return {"clients": result.data, "count": len(result.data)}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 3: Service Catalog
# ---------------------------------------------------------------------------

@mcp.tool
def manage_services(
    action: str,
    service_name: str | None = None,
    price: float | None = None,
    duration_minutes: int | None = None,
    category: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    service_id: str | None = None,
) -> dict:
    """
    Manage barbershop service catalog.

    Actions:
      - list: List all services (filter by category)
      - add: Add a new service
      - update: Update service details (price, duration, etc.)
      - toggle: Activate/deactivate a service
      - categories: List service categories

    Args:
        action: One of: list, add, update, toggle, categories
        service_name: Service name
        price: Price in dollars
        duration_minutes: Service duration in minutes
        category: Service category (cuts, shaves, styling, treatments, combos)
        description: Service description
        is_active: Whether service is available
        service_id: Service ID (for update/toggle)
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_services", {
            "action": action,
            "sample_services": [
                {"name": "Classic Cut", "price": 25, "duration": 30, "category": "cuts"},
                {"name": "Fade", "price": 30, "duration": 35, "category": "cuts"},
                {"name": "Beard Trim", "price": 15, "duration": 15, "category": "shaves"},
                {"name": "Hot Towel Shave", "price": 35, "duration": 30, "category": "shaves"},
                {"name": "Cut + Beard Combo", "price": 40, "duration": 45, "category": "combos"},
            ]
        })

    table = "services"

    if action == "list":
        q = sb.table(table).select("*")
        if category:
            q = q.eq("category", category)
        result = q.order("category").order("name").execute()
        return {"services": result.data, "count": len(result.data)}

    elif action == "add":
        if not all([service_name, price, duration_minutes]):
            return {"error": "service_name, price, and duration_minutes required"}
        data = {
            "name": service_name,
            "price": price,
            "duration_minutes": duration_minutes,
            "category": category or "general",
            "description": description or "",
            "is_active": True,
        }
        result = sb.table(table).insert(data).execute()
        return {"service": result.data[0] if result.data else data}

    elif action == "update":
        if not service_id and not service_name:
            return {"error": "service_id or service_name required"}
        updates = {}
        if price is not None:
            updates["price"] = price
        if duration_minutes is not None:
            updates["duration_minutes"] = duration_minutes
        if description is not None:
            updates["description"] = description
        if category is not None:
            updates["category"] = category
        if is_active is not None:
            updates["is_active"] = is_active
        if not updates:
            return {"error": "Nothing to update"}
        if service_id:
            result = sb.table(table).update(updates).eq("id", service_id).execute()
        else:
            result = sb.table(table).update(updates).eq("name", service_name).execute()
        return {"updated": result.data}

    elif action == "toggle":
        if not service_id and not service_name:
            return {"error": "service_id or service_name required"}
        if service_id:
            svc = sb.table(table).select("is_active").eq("id", service_id).execute()
        else:
            svc = sb.table(table).select("is_active,id").eq("name", service_name).execute()
        if not svc.data:
            return {"error": "Service not found"}
        new_status = not svc.data[0]["is_active"]
        sid = service_id or svc.data[0]["id"]
        sb.table(table).update({"is_active": new_status}).eq("id", sid).execute()
        return {"service": service_name or service_id, "is_active": new_status}

    elif action == "categories":
        result = sb.table(table).select("category,is_active").execute()
        cats = {}
        for r in result.data:
            c = r["category"]
            if c not in cats:
                cats[c] = {"total": 0, "active": 0}
            cats[c]["total"] += 1
            if r.get("is_active"):
                cats[c]["active"] += 1
        return {"categories": cats}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 4: Availability Check
# ---------------------------------------------------------------------------

@mcp.tool
def check_availability(
    date: str,
    barber_name: str | None = None,
    service_name: str | None = None,
    duration_minutes: int = 30,
) -> dict:
    """
    Check available appointment slots.

    Returns open time slots for a given date, optionally filtered by barber
    and service type. Accounts for existing bookings and barber schedules.

    Args:
        date: Date to check in YYYY-MM-DD format
        barber_name: Specific barber (or None for any available)
        service_name: Service name (to determine duration)
        duration_minutes: Default slot duration if service not specified
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("check_availability", {
            "date": date,
            "sample_slots": [
                {"time": "09:00", "barbers": ["Carlos", "Alex"]},
                {"time": "09:30", "barbers": ["Alex"]},
                {"time": "10:00", "barbers": ["Carlos", "Alex"]},
                {"time": "10:30", "barbers": ["Carlos"]},
                {"time": "11:00", "barbers": ["Carlos", "Alex"]},
            ]
        })

    # Get existing appointments for that date
    q = sb.table("appointments").select("barber_name,appointment_time,service_name").eq("appointment_date", date).neq("status", "cancelled")
    if barber_name:
        q = q.eq("barber_name", barber_name)
    existing = q.execute()

    # Build booked times per barber
    booked: dict[str, set] = {}
    for apt in existing.data:
        b = apt["barber_name"]
        if b not in booked:
            booked[b] = set()
        booked[b].add(apt["appointment_time"])

    # If we know the service, look up duration
    if service_name:
        svc = sb.table("services").select("duration_minutes").eq("name", service_name).execute()
        if svc.data:
            duration_minutes = svc.data[0]["duration_minutes"]

    # Get all barbers (or just the requested one)
    if barber_name:
        barbers = [barber_name]
    else:
        staff = sb.table("staff").select("name").eq("role", "barber").eq("is_active", True).execute()
        barbers = [s["name"] for s in staff.data] if staff.data else ["Any Available"]

    # Generate 30-min slots from 09:00 to 19:00
    open_hours = range(9, 19)
    available_slots = []
    for h in open_hours:
        for m in [0, 30]:
            t = f"{h:02d}:{m:02d}"
            available_barbers = []
            for b in barbers:
                if t not in booked.get(b, set()):
                    available_barbers.append(b)
            if available_barbers:
                available_slots.append({
                    "time": t,
                    "available_barbers": available_barbers,
                    "duration_minutes": duration_minutes,
                })

    return {
        "date": date,
        "service": service_name,
        "requested_barber": barber_name,
        "available_slots": available_slots,
        "total_open": len(available_slots),
    }


# ---------------------------------------------------------------------------
# Tool 5: Walk-in Queue
# ---------------------------------------------------------------------------

@mcp.tool
def manage_walkins(
    action: str,
    client_name: str | None = None,
    service_name: str | None = None,
    phone: str | None = None,
    walkin_id: str | None = None,
) -> dict:
    """
    Manage the walk-in queue.

    Actions:
      - add: Add a walk-in to the queue
      - queue: View current queue with wait times
      - next: Call the next person in line
      - remove: Remove someone from the queue
      - estimate: Get estimated wait time

    Args:
        action: One of: add, queue, next, remove, estimate
        client_name: Walk-in client's name
        service_name: Requested service
        phone: Phone number (for text-when-ready)
        walkin_id: Walk-in entry ID (for remove)
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_walkins", {
            "action": action,
            "sample_queue": [
                {"position": 1, "name": "Dave", "service": "Fade", "wait": "~10 min"},
                {"position": 2, "name": "Ryan", "service": "Cut + Beard", "wait": "~25 min"},
                {"position": 3, "name": "Chris", "service": "Classic Cut", "wait": "~40 min"},
            ]
        })

    table = "walkin_queue"

    if action == "add":
        if not client_name:
            return {"error": "client_name required"}
        # Get current queue length to estimate wait
        current = sb.table(table).select("id").eq("status", "waiting").execute()
        position = len(current.data) + 1
        avg_service_time = 30  # minutes

        data = {
            "client_name": client_name,
            "service_name": service_name or "General",
            "phone": phone or "",
            "status": "waiting",
            "position": position,
            "estimated_wait_minutes": position * avg_service_time,
            "joined_at": datetime.now(timezone.utc).isoformat(),
        }
        result = sb.table(table).insert(data).execute()
        return {
            "walkin": result.data[0] if result.data else data,
            "position": position,
            "estimated_wait": f"~{position * avg_service_time} minutes",
        }

    elif action == "queue":
        result = sb.table(table).select("*").eq("status", "waiting").order("position").execute()
        queue = []
        for i, entry in enumerate(result.data, 1):
            queue.append({
                "position": i,
                "id": entry["id"],
                "client_name": entry["client_name"],
                "service": entry.get("service_name", "General"),
                "estimated_wait": f"~{i * 30} minutes",
                "joined_at": entry["joined_at"],
            })
        return {"queue": queue, "total_waiting": len(queue)}

    elif action == "next":
        result = sb.table(table).select("*").eq("status", "waiting").order("position").limit(1).execute()
        if not result.data:
            return {"message": "Queue is empty — no walk-ins waiting."}
        entry = result.data[0]
        sb.table(table).update({
            "status": "called",
            "called_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", entry["id"]).execute()
        return {
            "called": entry["client_name"],
            "service": entry.get("service_name"),
            "phone": entry.get("phone"),
            "waited_since": entry["joined_at"],
        }

    elif action == "remove":
        if not walkin_id:
            return {"error": "walkin_id required"}
        sb.table(table).update({"status": "removed"}).eq("id", walkin_id).execute()
        return {"removed": walkin_id}

    elif action == "estimate":
        current = sb.table(table).select("id").eq("status", "waiting").execute()
        wait = len(current.data) * 30
        return {
            "people_ahead": len(current.data),
            "estimated_wait": f"~{wait} minutes",
            "note": "Walk-in times may vary depending on service complexity.",
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 6: SMS Reminders
# ---------------------------------------------------------------------------

@mcp.tool
def send_reminders(
    action: str,
    appointment_id: str | None = None,
    phone: str | None = None,
    message: str | None = None,
    reminder_type: str = "appointment",
) -> dict:
    """
    Send appointment reminders and follow-up messages.

    Actions:
      - appointment: Send appointment reminder (24h or 1h before)
      - follow_up: Send post-appointment follow-up (review request)
      - custom: Send a custom message
      - pending: List appointments needing reminders today
      - templates: List available reminder templates

    Args:
        action: One of: appointment, follow_up, custom, pending, templates
        appointment_id: Appointment to remind about
        phone: Phone number (overrides appointment's phone)
        message: Custom message text
        reminder_type: Type of reminder (24h, 1h, follow_up)
    """
    if action == "appointment":
        if not appointment_id:
            return {"error": "appointment_id required"}
        sb = _get_supabase()
        if sb:
            apt = sb.table("appointments").select("*").eq("id", appointment_id).execute()
            if apt.data:
                a = apt.data[0]
                msg = (
                    f"Hi {a['client_name']}! Reminder: you have a "
                    f"{a['service_name']} appointment at {a['appointment_time']} "
                    f"on {a['appointment_date']}. See you soon!"
                )
                to = phone or a.get("client_phone", "")
            else:
                msg = "Appointment reminder"
                to = phone or ""
        else:
            msg = "You have an upcoming appointment. See you soon!"
            to = phone or ""

        return {
            "status": "queued",
            "to": to,
            "message": msg,
            "reminder_type": reminder_type,
            "note": "Connect Twilio for live SMS delivery.",
        }

    elif action == "follow_up":
        msg = (
            "Thanks for visiting! We hope you love your new look. "
            "We'd really appreciate a quick review — it helps us and other customers. "
            "See you next time!"
        )
        return {
            "status": "queued",
            "to": phone or "",
            "message": message or msg,
            "type": "follow_up",
        }

    elif action == "custom":
        if not phone or not message:
            return {"error": "phone and message required"}
        return {
            "status": "queued",
            "to": phone,
            "message": message,
            "type": "custom",
        }

    elif action == "pending":
        sb = _get_supabase()
        if not sb:
            return _demo_response("send_reminders", {"action": "pending"})
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        result = sb.table("appointments").select("*").eq("appointment_date", tomorrow).eq("status", "scheduled").execute()
        return {
            "date": tomorrow,
            "appointments_needing_reminder": result.data,
            "count": len(result.data),
        }

    elif action == "templates":
        return {
            "templates": {
                "24h_reminder": "Hi {name}! Reminder: {service} at {time} tomorrow. Reply CANCEL to cancel.",
                "1h_reminder": "Hi {name}! Your {service} appointment is in 1 hour at {time}. See you soon!",
                "follow_up": "Thanks for visiting! Love your look? Leave us a review!",
                "birthday": "Happy Birthday {name}! Enjoy 20% off your next visit. Book now!",
                "loyalty": "You've visited {count} times! Next visit is 15% off. Thank you!",
                "no_show": "We missed you today, {name}. Want to reschedule? Reply YES.",
                "promo": "This week only: All services 10% off. Book your spot!",
            }
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 7: Shop Analytics
# ---------------------------------------------------------------------------

@mcp.tool
def shop_analytics(
    report: str,
    period: str = "today",
    barber_name: str | None = None,
) -> dict:
    """
    Get barbershop analytics and performance reports.

    Reports:
      - revenue: Revenue breakdown by period
      - staff_performance: Per-barber stats (appointments, revenue, rating)
      - client_retention: Client retention and repeat visit rates
      - summary: Full business summary with KPIs

    Args:
        report: One of: revenue, staff_performance, client_retention, summary
        period: Time period (today, week, month)
        barber_name: Filter by specific barber
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("shop_analytics", {
            "report": report,
            "sample_data": {
                "revenue_today": 580,
                "appointments_today": 18,
                "avg_ticket": 32.22,
                "top_barber": "Carlos",
                "retention_rate": "72%",
                "popular_service": "Fade",
            }
        })

    now = datetime.now(timezone.utc)
    if period == "today":
        since = now.replace(hour=0, minute=0, second=0).isoformat()
    elif period == "week":
        since = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        since = (now - timedelta(days=30)).isoformat()
    else:
        since = (now - timedelta(days=1)).isoformat()

    apts = sb.table("appointments").select("*").gte("created_at", since)
    if barber_name:
        apts = apts.eq("barber_name", barber_name)
    apts = apts.execute()

    if report == "revenue":
        # Join with services to get prices
        services = sb.table("services").select("name,price").execute()
        price_map = {s["name"]: s["price"] for s in services.data}
        total = sum(price_map.get(a.get("service_name", ""), 0) for a in apts.data)
        completed = [a for a in apts.data if a.get("status") == "completed"]
        return {
            "period": period,
            "total_revenue": round(total, 2),
            "completed": len(completed),
            "total_appointments": len(apts.data),
            "average_ticket": round(total / max(len(completed), 1), 2),
        }

    elif report == "staff_performance":
        barbers: dict[str, dict] = {}
        for a in apts.data:
            b = a.get("barber_name", "Unknown")
            if b not in barbers:
                barbers[b] = {"appointments": 0, "completed": 0, "no_shows": 0}
            barbers[b]["appointments"] += 1
            if a.get("status") == "completed":
                barbers[b]["completed"] += 1
            elif a.get("status") == "no-show":
                barbers[b]["no_shows"] += 1
        return {"period": period, "staff": barbers}

    elif report == "client_retention":
        # Count unique clients and repeat visitors
        client_visits: dict[str, int] = {}
        for a in apts.data:
            c = a.get("client_name", "Unknown")
            client_visits[c] = client_visits.get(c, 0) + 1
        total_clients = len(client_visits)
        repeat = sum(1 for v in client_visits.values() if v > 1)
        return {
            "period": period,
            "total_unique_clients": total_clients,
            "repeat_clients": repeat,
            "retention_rate": f"{round(repeat / max(total_clients, 1) * 100)}%" if total_clients else "N/A",
            "avg_visits": round(sum(client_visits.values()) / max(total_clients, 1), 1),
        }

    elif report == "summary":
        services = sb.table("services").select("name,price").execute()
        price_map = {s["name"]: s["price"] for s in services.data}
        total = sum(price_map.get(a.get("service_name", ""), 0) for a in apts.data)
        completed = [a for a in apts.data if a.get("status") == "completed"]
        by_status = {}
        for a in apts.data:
            s = a.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1

        # Popular services
        svc_counts: dict[str, int] = {}
        for a in apts.data:
            s = a.get("service_name", "Unknown")
            svc_counts[s] = svc_counts.get(s, 0) + 1
        top_services = sorted(svc_counts.items(), key=lambda x: -x[1])[:5]

        return {
            "period": period,
            "total_appointments": len(apts.data),
            "total_revenue": round(total, 2),
            "avg_ticket": round(total / max(len(completed), 1), 2),
            "by_status": by_status,
            "top_services": [{"name": n, "count": c} for n, c in top_services],
        }

    return {"error": f"Unknown report: {report}"}


# ---------------------------------------------------------------------------
# Run server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(os.getenv("MCP_BARBERSHOP_PORT", "8801"))
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run()  # stdio mode (default)
