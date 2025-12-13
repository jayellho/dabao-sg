#!/usr/bin/env python3
"""
Check EZCater Subscriptions

This script shows your current webhook subscriptions with EZCater.
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ez_graphql_endpoint = os.getenv("EZ_GRAPHQL_ENDPOINT")

def check_subscriptions():
    """Check current EZCater webhook subscriptions"""
    api_token = os.getenv("EZ_API_TOKEN")
    if not api_token:
        print("❌ EZ_API_TOKEN not found in .env file")
        return False
    
    print("🔍 Checking your EZCater subscriptions...")
    
    query = '''
    {
      subscribers {
        id
        name
        webhookUrl
        subscriptions {
          eventEntity
          eventKey
          parentEntity
          parentId
        }
      }
    }
    '''
    
    try:
        response = requests.post(
            ez_graphql_endpoint,
            json={'query': query},
            headers={
                'Authorization': api_token,
                'Content-Type': 'application/json'
            }
        )
        
        result = response.json()
        
        if 'errors' in result:
            print(f"❌ Error: {result['errors']}")
            return False
        
        subscribers = result.get('data', {}).get('subscribers', [])
        
        if not subscribers:
            print("❌ No webhook subscriptions found")
            print("\n💡 To set up subscriptions, run:")
            print("python setup_ezcater_webhooks.py https://your-webhook-url.com/webhook/ezcater")
            return False
        
        print(f"✅ Found {len(subscribers)} webhook subscriber(s):")
        print()
        
        for i, subscriber in enumerate(subscribers, 1):
            print(f"📡 Subscriber #{i}:")
            print(f"   ID: {subscriber['id']}")
            print(f"   Name: {subscriber['name']}")
            print(f"   Webhook URL: {subscriber['webhookUrl']}")
            
            subscriptions = subscriber.get('subscriptions', [])
            if subscriptions:
                print(f"   📋 Subscriptions ({len(subscriptions)}):")
                for sub in subscriptions:
                    print(f"      - {sub['eventEntity']}.{sub['eventKey']} (Parent: {sub['parentEntity']})")
            else:
                print("   ⚠️  No active subscriptions")
            print()
        
        # Save detailed info to file
        with open('current_subscriptions.json', 'w') as f:
            json.dump(result, f, indent=2)
        
        print("💾 Detailed subscription info saved to: current_subscriptions.json")
        return True
        
    except Exception as e:
        print(f"❌ Failed to check subscriptions: {e}")
        return False

if __name__ == '__main__':
    success = check_subscriptions()
    
    if success:
        print("\n🎯 Your webhook subscriptions are active!")
        print("🚀 Make sure your webhook server is running:")
        print("   python simple_ezcater_webhook.py")
    else:
        print("\n❌ No active subscriptions found.")
        print("🔧 Run the setup script first:")
        print("   python setup_ezcater_webhooks.py https://your-webhook-url:your-exposed-port-num/webhook/ezcater")
