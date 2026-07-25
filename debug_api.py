import json
import datetime
from naver_api import NaverCommerceAPI

def debug_fetch():
    api = NaverCommerceAPI()
    print("=== DEBUG NAVER COMMERCE API ===")
    print("Client ID:", api.client_id)
    
    token = api.get_access_token()
    print("Access Token Acquired:", bool(token))
    if not token:
        print("Token is None! Check credentials.")
        return

    raw_orders = api.fetch_product_orders(days=10)
    print("\n[Raw Response Summary]")
    data = raw_orders.get("data", {}) if raw_orders else {}
    items = data.get("lastChangeStatuses", []) if isinstance(data, dict) else []
    print(f"Total raw status change items found in past 10 days: {len(items)}")
    
    # Print distinct status types found
    status_types = set()
    for item in items:
        if isinstance(item, dict):
            st = item.get("lastChangedType", item.get("productOrderStatus", "UNKNOWN"))
            status_types.add(st)
            
    print("Distinct Status Types returned by Naver:", status_types)
    print("\nFirst 5 raw items:")
    print(json.dumps(items[:5], indent=2, ensure_ascii=False))

    # Save to debug_output.json
    with open("debug_output.json", "w", encoding="utf-8") as f:
        json.dump(raw_orders, f, indent=2, ensure_ascii=False)
    print("\nSaved full raw output to debug_output.json")

if __name__ == "__main__":
    debug_fetch()
