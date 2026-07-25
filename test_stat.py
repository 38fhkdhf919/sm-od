import sys
from naver_api import NaverCommerceAPI, extract_product_order_ids, extract_orders_list
from order_formatter import group_orders_by_order_id

sys.stdout.reconfigure(encoding='utf-8')

api = NaverCommerceAPI()
raw = api.fetch_product_orders(days=10)

print("--- STATISTICAL CHECK ---")
counts = {}
for st in ['PAYED', 'PREPARING', 'DELIVERED', 'PURCHASE_DECIDED', 'ALL']:
    pids = extract_product_order_ids(raw, status_filter=st)
    details = api.query_order_details(pids) if pids else {}
    orders = extract_orders_list(details, status_filter=st) if details else []
    grouped = group_orders_by_order_id(orders)
    names = [g.get('recipientName', '') for g in grouped]
    counts[st] = len(grouped)
    print(f"Status [{st:16s}]: {len(grouped)} orders -> {names}")

sum_sub = counts['PAYED'] + counts['PREPARING'] + counts['DELIVERED'] + counts['PURCHASE_DECIDED']
print(f"\nSum of 4 tabs: {sum_sub}, 'ALL' tab count: {counts['ALL']}")
