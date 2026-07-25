import os
import json
from flask import Flask, render_template, jsonify, request
from naver_api import (
    NaverCommerceAPI, 
    extract_product_order_ids, 
    extract_orders_list, 
    get_mock_orders
)
from order_formatter import format_order_to_text, group_orders_by_order_id

app = Flask(__name__, template_folder="templates")
api = NaverCommerceAPI()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/orders", methods=["GET"])
def get_orders():
    try:
        is_mock = request.args.get("mock", "true").lower() == "true"
        status_filter = request.args.get("status", "PAYED").upper()
        days = int(request.args.get("days", 10))
        
        raw_orders_list = []
        error_msg = None

        if not is_mock:
            raw_orders = api.fetch_product_orders(days=days)
            if api.last_error:
                error_msg = api.last_error
            else:
                product_order_ids = extract_product_order_ids(raw_orders, status_filter=status_filter)
                if product_order_ids:
                    orders_detail = api.query_order_details(product_order_ids)
                    raw_orders_list = extract_orders_list(orders_detail, status_filter=status_filter)

        # Fallback to mock if requested
        if is_mock:
            raw_orders_list = get_mock_orders(status_filter=status_filter)

        # Group multiple product orders belonging to the SAME master orderId
        grouped_orders = group_orders_by_order_id(raw_orders_list)

        formatted_orders = []
        for order in grouped_orders:
            formatted_orders.append({
                "raw": order,
                "formattedText": format_order_to_text(order)
            })

        return jsonify({
            "success": True,
            "error": error_msg,
            "isMock": is_mock,
            "statusFilter": status_filter,
            "orders": formatted_orders
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"서버 연동 오류: {str(e)}",
            "orders": []
        })

if __name__ == "__main__":
    print("==================================================")
    print(" 🚀 스마트스토어 주문 정리 웹 서버가 시작되었습니다.")
    print(" 🌐 접속 주소: http://127.0.0.1:5000")
    print("==================================================")
    app.run(host="0.0.0.0", port=5000, debug=True)
