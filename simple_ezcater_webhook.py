#!/usr/bin/env python3
"""
Simple EZCater Webhook Server

A minimal webhook server that receives EZCater order notifications
and syncs them to Google Calendar.
"""

import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from datetime import timedelta

# Import existing modules
from core_types import Order, OrderItem
from gcalclient import GoogleCalendarClient

# Load environment
load_dotenv()

# Simple configuration
API_TOKEN = os.getenv("EZ_API_TOKEN")
CALENDAR_ID = os.getenv("CALENDAR_ID")

# Initialize Flask app
app = Flask(__name__)

# Initialize Google Calendar client
calendar_client = GoogleCalendarClient() if CALENDAR_ID else None

def normalise_iso(ts: str | None) -> str | None:
    if not ts:
        return None
    # Convert 'Z' to '+00:00' so datetime.fromisoformat can parse it
    if ts.endswith("Z"):
        return ts[:-1] + "+00:00"
    return ts

def create_order_from_webhook(notification):
    order_id = notification.get('entity_id', 'unknown')
    occurred_at = notification.get('occurred_at', '')

    delivery_iso = normalise_iso(occurred_at)

    return Order(
        atg_order_id=order_id,
        po_id=f"EZ-{order_id[:8]}",
        vendor_name="EZCater",
        customer_name="Customer",
        address="Delivery Address",
        delivery_info="",
        delivery_instructions="",
        delivery_time_raw=occurred_at,
        delivery_iso=delivery_iso,
        delivery_date=(datetime.now().date().isoformat() if not delivery_iso else delivery_iso[:10]),
        delivery_time_24h=datetime.now().time().strftime("%H:%M"),
        number_of_people="",
        cost_per_person="",
        pricing={},
        items=[],
        page_number=0,
        row_number=0,
        order_sequence=0
    )



def build_ezcater_event_body(order: Order,
                             tz_name: str = "America/Los_Angeles",
                             default_duration_minutes: int = 60) -> dict | None:
    """
    Build a Google Calendar event body for an EZCater order.
    Mirrors the ATG build_calendar_event_body pattern.
    """

    identifier = f"EZ-{order.atg_order_id}" if order.atg_order_id else None
    if not identifier or not order.delivery_iso:
        return None

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/Los_Angeles")

    try:
        start_dt = datetime.fromisoformat(order.delivery_iso)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=tz)
    except Exception:
        return None

    end_dt = start_dt + timedelta(minutes=default_duration_minutes)

    title = f"{identifier} - {order.customer_name or 'Customer'}"

    description_lines = [
        f"EZCater order received",
        f"Order ID: {order.atg_order_id}",
        "=" * 40,
        f"Delivery instructions:\n{order.delivery_instructions or 'N/A'}"
    ]

    return {
        "summary": title,
        "location": order.address or "",
        "description": "\n".join(description_lines),
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz.key},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz.key},
        "extendedProperties": {
            "private": {
                "order_key": identifier   # <-- critical: matches ATG design
            }
        },
    }

def sync_to_calendar(order):
    """Sync order to Google Calendar"""
    if not calendar_client or not CALENDAR_ID:
        print("Calendar not configured: calendar_client or CALENDAR_ID missing")
        return False

    try:
        event_body = build_ezcater_event_body(order, tz_name="America/Los_Angeles")
        if not event_body:
            print("Skipping calendar sync: event_body is None (missing delivery_iso or id)")
            return False

        print("About to upsert EZCater event:")
        print(json.dumps(event_body, indent=2))

        changes = calendar_client.upsert_events(
            calendar_id=CALENDAR_ID,
            orders=[order],
            body_builder=lambda o: event_body,
            days_before=30,
            days_after=30,
            tz_name="America/Los_Angeles"
        )

        print(f"Calendar sync succeeded, {len(changes)} change(s).")
        return len(changes) > 0
    except Exception as e:
        print(f"Calendar sync failed: {e}")
        return False


@app.route('/webhook/ezcater', methods=['POST'])
def ezcater_webhook():
    """Handle EZCater webhook notifications"""
    try:
        notification = request.get_json()
        
        # Log the notification
        print(f"Received: {notification.get('entity_type')}.{notification.get('key')} for {notification.get('entity_id')}")
        
        # Save notification for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"webhook_{timestamp}.json", 'w') as f:
            json.dump(notification, f, indent=2)
        
        # Process order notifications
        if notification.get('entity_type') == 'Order':
            order = create_order_from_webhook(notification)
            calendar_success = sync_to_calendar(order)
            
            return jsonify({
                "status": "success",
                "order_id": order.atg_order_id,
                "calendar_synced": calendar_success
            })
        
        return jsonify({"status": "ignored"})
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "calendar_configured": calendar_client is not None
    })

if __name__ == '__main__':
    # Get port from environment (Railway sets this automatically)
    port = int(os.getenv('PORT', 5000))
    
    print("Starting simple EZCater webhook server...")
    print(f"Webhook URL: http://0.0.0.0:{port}/webhook/ezcater")
    print("Health check: /health")
    
    # Run with Railway-compatible settings
    app.run(host='0.0.0.0', port=port, debug=False)
