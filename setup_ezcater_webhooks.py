#!/usr/bin/env python3
"""
Simple EZCater Webhook Setup

One-time setup script to register your webhook URL with EZCater.
"""

import os
import requests
import json
from dotenv import load_dotenv
import sys

load_dotenv()

# Get environment variables.
ez_graphql_endpoint = os.getenv("EZ_GRAPHQL_ENDPOINT")
api_token = os.getenv("EZ_API_TOKEN")

# Centralized HTTP and error handling.
def gql(headers: dict, query: str, ez_graphql_endpoint: str) -> dict:
    """Send a GraphQL query/mutation and return parsed JSON."""
    if not ez_graphql_endpoint:
        raise RuntimeError("EZ_GRAPHQL_ENDPOINT is not set.")
    
    resp = requests.post(ez_graphql_endpoint, json={"query": query}, headers=headers, timeout=30)
    try:
        data = resp.json()
    except Exception:
        print("❌ Non-JSON response from server")
        print("HTTP:", resp.status_code)
        print(resp.text)
        raise

    if resp.status_code >= 400:
        print("❌ HTTP error:", resp.status_code)
        print(json.dumps(data, indent=2))
        resp.raise_for_status()

    return data

# Get subscriber if exists
def get_first_subscriber(headers: dict, ez_graphql_endpoint: str) -> dict | None:
    query = """
    query allSubscribers {
      subscribers {
        id
        name
        webhookUrl
      }
    }
    """
    data = gql(headers, query, ez_graphql_endpoint)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    subs = data.get("data", {}).get("subscribers", []) or []
    return subs[0] if subs else None

def get_first_caterer(headers: dict, ez_graphql_endpoint: str) -> tuple[str, str]:
    query = """
    {
      caterers {
        uuid
        name
      }
    }
    """
    data = gql(headers, query, ez_graphql_endpoint)
    if "errors" in data:
        raise RuntimeError(f"caterers query failed: {data['errors']}")

    caterers = data.get("data", {}).get("caterers", []) or []
    if not caterers:
        raise RuntimeError("No caterers found for this API token/user.")
    return caterers[0]["uuid"], caterers[0]["name"]

def create_subscriber(headers: dict, name: str, webhook_url: str, ez_graphql_endpoint: str) -> dict:
    mutation = f"""
    mutation createSubscriber {{
      createSubscriber(subscriberParams: {{
        name: "{name}",
        webhookUrl: "{webhook_url}"
      }}) {{
        subscriber {{
          id
          name
          webhookUrl
        }}
      }}
    }}
    """
    data = gql(headers, mutation, ez_graphql_endpoint)
    if "errors" in data:
        raise RuntimeError(f"createSubscriber failed: {data['errors']}")
    return data["data"]["createSubscriber"]["subscriber"]

def update_subscriber(headers: dict, subscriber_id: str, webhook_url: str, ez_graphql_endpoint: str) -> dict:
    mutation = f"""
    mutation updateSubscriber {{
      updateSubscriber(
        subscriberId: "{subscriber_id}",
        subscriberParams: {{
          webhookUrl: "{webhook_url}"
        }}
      ) {{
        subscriber {{
          id
          name
          webhookUrl
        }}
      }}
    }}
    """
    data = gql(headers, mutation, ez_graphql_endpoint)
    if "errors" in data:
        raise RuntimeError(f"updateSubscriber failed: {data['errors']}")
    return data["data"]["updateSubscriber"]["subscriber"]

def create_subscription(headers: dict, subscriber_id: str, caterer_uuid: str, event_key: str, ez_graphql_endpoint: str) -> None:
    mutation = f"""
    mutation createSubscription {{
      createSubscription(subscriptionParams: {{
        eventEntity: Order,
        eventKey: {event_key},
        parentEntity: Caterer,
        parentId: "{caterer_uuid}",
        subscriberId: "{subscriber_id}"
      }}) {{
        subscription {{
          eventEntity
          eventKey
          parentEntity
          parentId
        }}
      }}
    }}
    """
    data = gql(headers, mutation, ez_graphql_endpoint)
    if "errors" in data:
        # not fatal; could already exist
        print(f"⚠️  Could not create subscription for {event_key}: {data['errors']}")
    else:
        print(f"✅ Subscription ensured: Order.{event_key} (Caterer {caterer_uuid})")

def setup_webhooks(webhook_url: str, api_token: str, ez_graphql_endpoint: str) -> bool:
    if not api_token:
        print("❌ EZ_API_TOKEN not found in .env file")
        return False

    headers = {
        "Content-Type": "application/json",
        "Authorization": api_token,
    }

    print(f"🔧 Setting up webhooks for: {webhook_url}")

    # 1) Create or update subscriber
    try:
        existing = get_first_subscriber(headers, ez_graphql_endpoint)
        if existing:
            print(f"ℹ️  Existing subscriber found: {existing['id']} ({existing.get('name')})")
            if existing.get("webhookUrl") != webhook_url:
                print("📝 Updating subscriber webhookUrl...")
                sub = update_subscriber(headers, existing["id"], webhook_url, ez_graphql_endpoint)
                print(f"✅ Updated subscriber webhookUrl to: {sub['webhookUrl']}")
            else:
                sub = existing
                print("✅ Subscriber webhookUrl already matches; no update needed.")
        else:
            print("📝 No subscriber found; creating one...")
            sub = create_subscriber(headers, "DabaoSG-Simple", webhook_url, ez_graphql_endpoint)
            print(f"✅ Created subscriber: {sub['id']}")
    except Exception as e:
        print(f"❌ Subscriber setup failed: {e}")
        return False

    subscriber_id = sub["id"]

    # 2) Caterer ID
    try:
        caterer_uuid, caterer_name = get_first_caterer(headers, ez_graphql_endpoint)
        print(f"🏪 Using caterer: {caterer_name} ({caterer_uuid})")
    except Exception as e:
        print(f"❌ Failed to fetch caterer: {e}")
        return False

    # 3) Subscriptions (supported keys)
    # Public API supports: accepted, cancelled (and menu updated events for Menu)
    events = ["accepted", "cancelled"]
    for event_key in events:
        print(f"📋 Ensuring subscription for Order.{event_key}...")
        create_subscription(headers, subscriber_id, caterer_uuid, event_key, ez_graphql_endpoint)

    print("\n🎉 Webhook setup complete!")
    print(f"📡 Webhook URL: {webhook_url}")
    print(f"🆔 Subscriber ID: {subscriber_id}")
    print(f"🏪 Caterer: {caterer_name}")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python setup_ezcater_webhooks.py <webhook_url>")
        print("Example: python setup_ezcater_webhooks.py http://<public-host>:5000/webhook/ezcater")
        sys.exit(1)

    ok = setup_webhooks(sys.argv[1], api_token, ez_graphql_endpoint)
    sys.exit(0 if ok else 1)
