"""
OpenClaw Restaurant MCP Server — 7 tools for restaurant operations.

Tools:
  1. manage_menu       — Add/update/remove items, toggle availability, bulk price updates
  2. manage_orders     — View orders, update status, search by customer
  3. manage_reservations — Create/update/cancel reservations, check availability
  4. respond_to_reviews — Draft professional responses to customer reviews
  5. customer_messaging — Send SMS/email to customers (order updates, promos)
  6. restaurant_analytics — Revenue, popular items, peak hours, trends
  7. social_media_post  — Generate social media content for the restaurant

Usage:
  python -m mcp_servers.restaurant.server          # stdio mode
  python -m mcp_servers.restaurant.server --http    # HTTP mode (port 8800)
"""

from __future__ import annotations

import os
import sys
import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "OpenClaw Restaurant Tools",
    version="1.0.0",
    instructions=(
        "Restaurant management MCP server by OpenClaw. "
        "Provides tools for menu management, order tracking, reservations, "
        "review responses, customer messaging, analytics, and social media."
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
    """Return demo data when no Supabase connected — useful for marketplace demos."""
    return {
        "status": "demo_mode",
        "tool": tool,
        "message": "Running in demo mode. Connect Supabase for live data.",
        "params_received": params,
        "demo_data": True,
    }


# ---------------------------------------------------------------------------
# Tool 1: Menu Management
# ---------------------------------------------------------------------------

@mcp.tool
def manage_menu(
    action: str,
    item_name: str | None = None,
    category: str | None = None,
    price: float | None = None,
    description: str | None = None,
    is_available: bool | None = None,
    search_query: str | None = None,
) -> dict:
    """
    Manage restaurant menu items.

    Actions:
      - list: List all menu items (filter by category)
      - search: Search items by name
      - add: Add a new menu item (requires name, category, price)
      - update: Update an existing item (by name)
      - toggle: Toggle item availability
      - categories: List all categories with item counts
      - price_update: Bulk update prices by category (price = percentage increase)

    Args:
        action: One of: list, search, add, update, toggle, categories, price_update
        item_name: Name of the menu item (for add/update/toggle)
        category: Menu category (for filtering or adding)
        price: Price in dollars (or percentage for price_update)
        description: Item description
        is_available: Whether item is available
        search_query: Search string for search action
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_menu", {
            "action": action, "item_name": item_name, "category": category,
            "sample_menu": [
                {"name": "Chicken Tikka Masala", "price": 16.99, "category": "Chicken", "available": True},
                {"name": "Garlic Naan", "price": 3.99, "category": "Breads", "available": True},
                {"name": "Mango Lassi", "price": 4.99, "category": "Beverages", "available": True},
            ]
        })

    table = "menu_items"

    if action == "list":
        q = sb.table(table).select("*")
        if category:
            q = q.eq("category", category)
        result = q.order("category").execute()
        return {"items": result.data, "count": len(result.data)}

    elif action == "search":
        if not search_query:
            return {"error": "search_query required for search action"}
        result = sb.table(table).select("*").ilike("name", f"%{search_query}%").execute()
        return {"items": result.data, "count": len(result.data)}

    elif action == "add":
        if not all([item_name, category, price]):
            return {"error": "item_name, category, and price required for add"}
        data = {
            "name": item_name,
            "category": category,
            "price": price,
            "description": description or "",
            "is_available": True if is_available is None else is_available,
        }
        result = sb.table(table).insert(data).execute()
        return {"added": result.data[0] if result.data else data}

    elif action == "update":
        if not item_name:
            return {"error": "item_name required for update"}
        updates = {}
        if price is not None:
            updates["price"] = price
        if description is not None:
            updates["description"] = description
        if is_available is not None:
            updates["is_available"] = is_available
        if category is not None:
            updates["category"] = category
        if not updates:
            return {"error": "Nothing to update — provide price, description, is_available, or category"}
        result = sb.table(table).update(updates).eq("name", item_name).execute()
        return {"updated": result.data}

    elif action == "toggle":
        if not item_name:
            return {"error": "item_name required for toggle"}
        item = sb.table(table).select("is_available").eq("name", item_name).execute()
        if not item.data:
            return {"error": f"Item '{item_name}' not found"}
        new_status = not item.data[0]["is_available"]
        sb.table(table).update({"is_available": new_status}).eq("name", item_name).execute()
        return {"item": item_name, "is_available": new_status}

    elif action == "categories":
        result = sb.table(table).select("category").execute()
        cats = {}
        for r in result.data:
            c = r["category"]
            cats[c] = cats.get(c, 0) + 1
        return {"categories": cats, "total_items": len(result.data)}

    elif action == "price_update":
        if not category or price is None:
            return {"error": "category and price (percentage increase) required"}
        items = sb.table(table).select("id,name,price").eq("category", category).execute()
        updated = []
        for item in items.data:
            new_price = round(item["price"] * (1 + price / 100), 2)
            sb.table(table).update({"price": new_price}).eq("id", item["id"]).execute()
            updated.append({"name": item["name"], "old": item["price"], "new": new_price})
        return {"category": category, "updated": updated, "count": len(updated)}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 2: Order Management
# ---------------------------------------------------------------------------

@mcp.tool
def manage_orders(
    action: str,
    order_id: str | None = None,
    status: str | None = None,
    customer_email: str | None = None,
    limit: int = 20,
) -> dict:
    """
    View and manage restaurant orders.

    Actions:
      - list: List recent orders (filter by status)
      - get: Get order details by ID
      - update_status: Update order status (received → preparing → ready → completed)
      - search: Search orders by customer email
      - stats: Order statistics (today, this week)

    Args:
        action: One of: list, get, update_status, search, stats
        order_id: Order UUID (for get/update_status)
        status: Order status filter or new status
        customer_email: Customer email for search
        limit: Max results (default 20)
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_orders", {
            "action": action,
            "sample_orders": [
                {"id": "ord-001", "customer": "John Doe", "status": "preparing", "total": 42.97, "items": 3},
                {"id": "ord-002", "customer": "Jane Smith", "status": "ready", "total": 28.50, "items": 2},
            ]
        })

    table = "orders"

    if action == "list":
        q = sb.table(table).select("*")
        if status:
            q = q.eq("status", status)
        result = q.order("created_at", desc=True).limit(limit).execute()
        return {"orders": result.data, "count": len(result.data)}

    elif action == "get":
        if not order_id:
            return {"error": "order_id required"}
        result = sb.table(table).select("*").eq("id", order_id).execute()
        return {"order": result.data[0] if result.data else None}

    elif action == "update_status":
        if not order_id or not status:
            return {"error": "order_id and status required"}
        valid = ["received", "preparing", "ready", "completed", "cancelled"]
        if status not in valid:
            return {"error": f"Invalid status. Must be one of: {valid}"}
        result = sb.table(table).update({
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", order_id).execute()
        return {"updated": result.data}

    elif action == "search":
        if not customer_email:
            return {"error": "customer_email required for search"}
        result = sb.table(table).select("*").eq("customer_email", customer_email).order("created_at", desc=True).limit(limit).execute()
        return {"orders": result.data, "count": len(result.data)}

    elif action == "stats":
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0).isoformat()
        week_start = (now - timedelta(days=7)).isoformat()

        today_orders = sb.table(table).select("id,total_amount,status").gte("created_at", today_start).execute()
        week_orders = sb.table(table).select("id,total_amount,status").gte("created_at", week_start).execute()

        def _stats(orders):
            total = sum(o.get("total_amount", 0) or 0 for o in orders)
            by_status = {}
            for o in orders:
                s = o.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
            return {"count": len(orders), "revenue": round(total, 2), "by_status": by_status}

        return {
            "today": _stats(today_orders.data),
            "this_week": _stats(week_orders.data),
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 3: Reservations
# ---------------------------------------------------------------------------

@mcp.tool
def manage_reservations(
    action: str,
    guest_name: str | None = None,
    guest_phone: str | None = None,
    guest_email: str | None = None,
    party_size: int | None = None,
    date: str | None = None,
    time: str | None = None,
    reservation_id: str | None = None,
    special_requests: str | None = None,
) -> dict:
    """
    Manage restaurant reservations.

    Actions:
      - create: Book a new reservation
      - list: List upcoming reservations (filter by date)
      - cancel: Cancel a reservation
      - update: Modify reservation details
      - availability: Check available time slots for a date/party size

    Args:
        action: One of: create, list, cancel, update, availability
        guest_name: Guest's name
        guest_phone: Guest's phone number
        guest_email: Guest's email
        party_size: Number of guests
        date: Date in YYYY-MM-DD format
        time: Time in HH:MM format (24h)
        reservation_id: Reservation ID (for cancel/update)
        special_requests: Special requests or notes
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("manage_reservations", {
            "action": action,
            "sample_slots": ["17:00", "17:30", "18:00", "18:30", "19:00", "19:30", "20:00", "20:30"],
            "sample_reservation": {
                "id": "res-001", "guest": "Miles", "party_size": 4,
                "date": "2026-03-10", "time": "19:00", "status": "confirmed"
            }
        })

    table = "reservations"

    if action == "create":
        if not all([guest_name, party_size, date, time]):
            return {"error": "guest_name, party_size, date, and time required"}
        data = {
            "guest_name": guest_name,
            "guest_phone": guest_phone or "",
            "guest_email": guest_email or "",
            "party_size": party_size,
            "reservation_date": date,
            "reservation_time": time,
            "special_requests": special_requests or "",
            "status": "confirmed",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        result = sb.table(table).insert(data).execute()
        return {"reservation": result.data[0] if result.data else data, "status": "confirmed"}

    elif action == "list":
        q = sb.table(table).select("*").eq("status", "confirmed")
        if date:
            q = q.eq("reservation_date", date)
        else:
            q = q.gte("reservation_date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        result = q.order("reservation_date").order("reservation_time").execute()
        return {"reservations": result.data, "count": len(result.data)}

    elif action == "cancel":
        if not reservation_id:
            return {"error": "reservation_id required"}
        result = sb.table(table).update({"status": "cancelled"}).eq("id", reservation_id).execute()
        return {"cancelled": result.data}

    elif action == "update":
        if not reservation_id:
            return {"error": "reservation_id required"}
        updates = {}
        if party_size:
            updates["party_size"] = party_size
        if date:
            updates["reservation_date"] = date
        if time:
            updates["reservation_time"] = time
        if special_requests:
            updates["special_requests"] = special_requests
        if guest_name:
            updates["guest_name"] = guest_name
        if not updates:
            return {"error": "Nothing to update"}
        result = sb.table(table).update(updates).eq("id", reservation_id).execute()
        return {"updated": result.data}

    elif action == "availability":
        if not date:
            return {"error": "date required for availability check"}
        # Get existing reservations for that date
        existing = sb.table(table).select("reservation_time,party_size").eq("reservation_date", date).eq("status", "confirmed").execute()
        booked_times = {r["reservation_time"] for r in existing.data}

        # Generate 30-min slots from 17:00 to 21:00
        max_capacity = int(os.getenv("RESTAURANT_CAPACITY", "50"))
        slots = []
        for h in range(17, 22):
            for m in [0, 30]:
                t = f"{h:02d}:{m:02d}"
                booked_at_time = sum(
                    r["party_size"] for r in existing.data if r["reservation_time"] == t
                )
                if booked_at_time < max_capacity:
                    slots.append({
                        "time": t,
                        "available_seats": max_capacity - booked_at_time,
                    })
        return {"date": date, "available_slots": slots, "party_size_requested": party_size}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 4: Review Response
# ---------------------------------------------------------------------------

@mcp.tool
def respond_to_reviews(
    action: str,
    review_text: str | None = None,
    reviewer_name: str | None = None,
    rating: int | None = None,
    platform: str = "google",
    tone: str = "professional",
) -> dict:
    """
    Draft professional responses to customer reviews.

    Actions:
      - draft_response: Generate a response to a customer review
      - analyze: Analyze review sentiment and key themes
      - template: Get a response template by rating level

    Args:
        action: One of: draft_response, analyze, template
        review_text: The customer's review text
        reviewer_name: The reviewer's name
        rating: Star rating (1-5)
        platform: Review platform (google, yelp, tripadvisor)
        tone: Response tone (professional, warm, apologetic)
    """
    if action == "draft_response":
        if not review_text:
            return {"error": "review_text required"}

        name = reviewer_name or "valued guest"
        stars = rating or 3

        if stars >= 4:
            response = (
                f"Thank you so much, {name}! We're thrilled you enjoyed your experience. "
                f"Your kind words mean the world to our team. We look forward to welcoming "
                f"you back soon!"
            )
        elif stars == 3:
            response = (
                f"Thank you for your feedback, {name}. We appreciate you taking the time "
                f"to share your experience. We're always looking to improve and would love "
                f"the opportunity to exceed your expectations on your next visit."
            )
        else:
            response = (
                f"Thank you for sharing your experience, {name}. We sincerely apologize "
                f"that we didn't meet your expectations. Your feedback is important to us, "
                f"and we'd love the chance to make it right. Please reach out to us directly "
                f"so we can address your concerns."
            )

        if tone == "warm":
            response = response.replace("Thank you", "We truly appreciate you")
        elif tone == "apologetic":
            response = f"We're deeply sorry to hear about your experience, {name}. " + response

        return {
            "response": response,
            "rating": stars,
            "tone": tone,
            "platform": platform,
            "reviewer": name,
            "tip": "Personalize this response with specific details from the review before posting.",
        }

    elif action == "analyze":
        if not review_text:
            return {"error": "review_text required"}

        # Simple keyword-based sentiment (real version would use AI)
        positive = ["great", "amazing", "excellent", "delicious", "wonderful", "best", "love", "fantastic", "perfect"]
        negative = ["bad", "terrible", "awful", "disgusting", "worst", "cold", "slow", "rude", "dirty", "disappointing"]

        text_lower = review_text.lower()
        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)

        sentiment = "positive" if pos_count > neg_count else "negative" if neg_count > pos_count else "neutral"
        themes = []
        if any(w in text_lower for w in ["food", "dish", "meal", "taste", "flavor", "delicious"]):
            themes.append("food_quality")
        if any(w in text_lower for w in ["service", "staff", "waiter", "server", "friendly", "rude"]):
            themes.append("service")
        if any(w in text_lower for w in ["ambiance", "atmosphere", "decor", "clean", "dirty", "music"]):
            themes.append("ambiance")
        if any(w in text_lower for w in ["price", "expensive", "cheap", "value", "worth", "cost"]):
            themes.append("value")
        if any(w in text_lower for w in ["wait", "slow", "fast", "quick", "time"]):
            themes.append("speed")

        return {
            "sentiment": sentiment,
            "themes": themes,
            "positive_signals": pos_count,
            "negative_signals": neg_count,
            "rating": rating,
            "urgency": "high" if sentiment == "negative" and (rating or 3) <= 2 else "normal",
        }

    elif action == "template":
        templates = {
            5: "Thank you for the amazing review, {name}! We're so glad you had a 5-star experience. We can't wait to see you again!",
            4: "Thanks for the great feedback, {name}! We're happy you enjoyed your visit. We'll keep working to make it even better!",
            3: "Thank you for visiting, {name}. We appreciate your honest feedback and will use it to improve. Hope to see you again!",
            2: "We're sorry your experience wasn't up to par, {name}. We take your feedback seriously and would love another chance to impress you.",
            1: "We sincerely apologize, {name}. This is not the experience we strive for. Please contact us directly so we can make things right.",
        }
        r = rating or 3
        return {"template": templates.get(r, templates[3]), "rating": r}

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 5: Customer Messaging
# ---------------------------------------------------------------------------

@mcp.tool
def customer_messaging(
    action: str,
    to: str | None = None,
    message: str | None = None,
    channel: str = "sms",
    template: str | None = None,
    order_id: str | None = None,
) -> dict:
    """
    Send messages to customers via SMS or email.

    Actions:
      - send: Send a message to a customer
      - order_update: Send an order status update
      - promo: Send a promotional message
      - templates: List available message templates

    Args:
        action: One of: send, order_update, promo, templates
        to: Customer phone number or email
        message: Message text (for send action)
        channel: Communication channel (sms or email)
        template: Template name (for templated messages)
        order_id: Order ID (for order_update action)
    """
    if action == "send":
        if not to or not message:
            return {"error": "to and message required"}
        # In production, this calls Twilio/SendGrid
        return {
            "status": "queued",
            "to": to,
            "channel": channel,
            "message": message,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "note": "Connect Twilio (SMS) or SendGrid (email) for live delivery.",
        }

    elif action == "order_update":
        if not to or not order_id:
            return {"error": "to and order_id required"}
        sb = _get_supabase()
        if sb:
            order = sb.table("orders").select("status,customer_name").eq("id", order_id).execute()
            if order.data:
                o = order.data[0]
                msg = f"Hi {o['customer_name']}! Your order #{order_id[:8]} is now {o['status']}."
                if o["status"] == "ready":
                    msg += " It's ready for pickup!"
            else:
                msg = f"Order update for #{order_id[:8]}."
        else:
            msg = f"Your order #{order_id[:8]} has been updated. Thank you for your order!"

        return {
            "status": "queued",
            "to": to,
            "channel": channel,
            "message": msg,
            "order_id": order_id,
        }

    elif action == "promo":
        if not to:
            return {"error": "to required"}
        promos = {
            "happy_hour": "Happy Hour special! 20% off all appetizers from 4-6 PM. Show this message to redeem.",
            "loyalty": "Thank you for being a loyal customer! Here's 15% off your next visit. Code: LOYAL15",
            "new_item": "We've added exciting new dishes to our menu! Come try them this week.",
            "birthday": "Happy Birthday! Enjoy a free dessert on us when you dine in this week.",
            "weekend": "Weekend special! Family platter for 4 at just $49.99. Reserve your table now!",
        }
        msg = promos.get(template, promos["happy_hour"])
        return {
            "status": "queued",
            "to": to,
            "channel": channel,
            "message": msg,
            "template": template or "happy_hour",
            "available_templates": list(promos.keys()),
        }

    elif action == "templates":
        return {
            "templates": {
                "happy_hour": "Happy Hour promotional message",
                "loyalty": "Loyalty reward / discount code",
                "new_item": "New menu item announcement",
                "birthday": "Birthday special offer",
                "weekend": "Weekend special deal",
                "order_received": "Order confirmation",
                "order_ready": "Order ready for pickup",
                "reservation_confirm": "Reservation confirmation",
                "reservation_reminder": "Reservation reminder (1 hour before)",
            }
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Tool 6: Analytics
# ---------------------------------------------------------------------------

@mcp.tool
def restaurant_analytics(
    report: str,
    period: str = "today",
    category: str | None = None,
) -> dict:
    """
    Get restaurant analytics and insights.

    Reports:
      - revenue: Revenue breakdown by period
      - popular_items: Most ordered items
      - peak_hours: Busiest hours of the day
      - summary: Full business summary

    Args:
        report: One of: revenue, popular_items, peak_hours, summary
        period: Time period (today, week, month)
        category: Filter by menu category
    """
    sb = _get_supabase()
    if not sb:
        return _demo_response("restaurant_analytics", {
            "report": report,
            "sample_data": {
                "revenue_today": 1247.50,
                "orders_today": 34,
                "avg_order": 36.69,
                "top_items": ["Chicken Tikka Masala", "Garlic Naan", "Lamb Biryani"],
                "peak_hour": "18:00-19:00",
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

    orders = sb.table("orders").select("*").gte("created_at", since).execute()

    if report == "revenue":
        total = sum(o.get("total_amount", 0) or 0 for o in orders.data)
        completed = [o for o in orders.data if o.get("status") == "completed"]
        return {
            "period": period,
            "total_revenue": round(total, 2),
            "completed_orders": len(completed),
            "total_orders": len(orders.data),
            "average_order": round(total / max(len(orders.data), 1), 2),
        }

    elif report == "popular_items":
        item_counts: dict[str, int] = {}
        for o in orders.data:
            items = o.get("order_items") or []
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except Exception:
                    items = []
            for item in items:
                name = item.get("name", "Unknown")
                qty = item.get("quantity", 1)
                item_counts[name] = item_counts.get(name, 0) + qty
        sorted_items = sorted(item_counts.items(), key=lambda x: -x[1])
        return {
            "period": period,
            "popular_items": [{"name": n, "orders": c} for n, c in sorted_items[:10]],
        }

    elif report == "peak_hours":
        hour_counts: dict[int, int] = {}
        for o in orders.data:
            ts = o.get("created_at", "")
            try:
                h = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
                hour_counts[h] = hour_counts.get(h, 0) + 1
            except Exception:
                pass
        sorted_hours = sorted(hour_counts.items(), key=lambda x: -x[1])
        return {
            "period": period,
            "peak_hours": [{"hour": f"{h:02d}:00", "orders": c} for h, c in sorted_hours[:5]],
        }

    elif report == "summary":
        total = sum(o.get("total_amount", 0) or 0 for o in orders.data)
        by_status = {}
        for o in orders.data:
            s = o.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "period": period,
            "total_orders": len(orders.data),
            "total_revenue": round(total, 2),
            "average_order": round(total / max(len(orders.data), 1), 2),
            "by_status": by_status,
        }

    return {"error": f"Unknown report: {report}"}


# ---------------------------------------------------------------------------
# Tool 7: Social Media
# ---------------------------------------------------------------------------

@mcp.tool
def social_media_post(
    action: str,
    topic: str | None = None,
    platform: str = "instagram",
    special_item: str | None = None,
    event_name: str | None = None,
    tone: str = "engaging",
) -> dict:
    """
    Generate social media content for the restaurant.

    Actions:
      - daily_special: Create a daily special post
      - event: Create an event announcement post
      - behind_scenes: Create a behind-the-scenes post
      - seasonal: Create a seasonal/holiday post
      - engagement: Create an engagement/question post

    Args:
        action: One of: daily_special, event, behind_scenes, seasonal, engagement
        topic: Topic or theme for the post
        platform: Target platform (instagram, facebook, twitter, tiktok)
        special_item: Featured menu item
        event_name: Event name (for event posts)
        tone: Post tone (engaging, elegant, fun, urgent)
    """
    char_limits = {"instagram": 2200, "facebook": 63206, "twitter": 280, "tiktok": 2200}
    limit = char_limits.get(platform, 2200)
    hashtags = "#foodie #restaurant #freshfood #eatlocal #supportlocal"

    if action == "daily_special":
        item = special_item or "Chef's Special"
        post = f"Today's special: {item}! Our chef has prepared something extraordinary just for you. Available while supplies last — don't miss out! {hashtags}"
        return {
            "post": post[:limit],
            "platform": platform,
            "type": "daily_special",
            "suggested_time": "11:00 AM (pre-lunch)",
            "image_suggestion": f"Close-up shot of {item} with warm lighting",
        }

    elif action == "event":
        name = event_name or "Special Event"
        post = f"Join us for {name}! An unforgettable evening awaits. Reserve your spot today — limited seats available. {hashtags} #event #finedining"
        return {
            "post": post[:limit],
            "platform": platform,
            "type": "event",
            "suggested_time": "5:00 PM (evening scroll)",
        }

    elif action == "behind_scenes":
        subject = topic or "kitchen prep"
        post = f"Ever wonder what happens behind the scenes? Here's a peek at our {subject}. Every dish is crafted with love and the freshest ingredients. {hashtags} #behindthescenes #cheflife"
        return {
            "post": post[:limit],
            "platform": platform,
            "type": "behind_scenes",
            "suggested_time": "2:00 PM (afternoon engagement)",
            "video_suggestion": f"30-60 second clip of {subject}",
        }

    elif action == "seasonal":
        season = topic or "spring"
        post = f"Celebrate {season} with our new seasonal menu! Fresh flavors and exciting dishes inspired by the season. Come taste the difference. {hashtags} #{season}menu #seasonal"
        return {
            "post": post[:limit],
            "platform": platform,
            "type": "seasonal",
            "suggested_time": "10:00 AM (morning visibility)",
        }

    elif action == "engagement":
        question = topic or "What's your go-to comfort food dish?"
        post = f"We want to hear from you! {question} Drop your answer below and you might see it on our menu next! {hashtags} #foodpoll #community"
        return {
            "post": post[:limit],
            "platform": platform,
            "type": "engagement",
            "suggested_time": "7:00 PM (peak engagement)",
        }

    return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Run server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--http" in sys.argv:
        port = int(os.getenv("MCP_RESTAURANT_PORT", "8800"))
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run()  # stdio mode (default)
