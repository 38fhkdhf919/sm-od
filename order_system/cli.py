import sys
import json
from naver_api import NaverCommerceAPI, get_mock_orders
from order_formatter import format_order_to_text

def main():
    print("==========================================")
    print(" 네이버 스마트스토어 주문 정보 정리 도구")
    print("==========================================\n")
    
    api = NaverCommerceAPI()
    orders = None
    
    # Try fetching real orders
    raw_orders = api.fetch_product_orders()
    if raw_orders and "data" in raw_orders:
        product_order_ids = [item["productOrderId"] for item in raw_orders.get("data", [])]
        if product_order_ids:
            orders_detail = api.query_order_details(product_order_ids)
            if orders_detail and "data" in orders_detail:
                orders = orders_detail["data"]
    
    if not orders:
        print("💡 [알림] 현재 들어온 신규 주문이 없거나 커머스 API 연동 준비 중입니다.")
        print("💡 테스트용 샘플 주문 양식을 출력합니다.\n")
        orders = get_mock_orders()

    for idx, order in enumerate(orders, 1):
        formatted_text = format_order_to_text(order)
        print(f"--- [주문 #{idx}] ---")
        print(formatted_text)
        print("\n" + "="*40 + "\n")

if __name__ == "__main__":
    main()
