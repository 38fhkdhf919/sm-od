import os
import sys
import json
import time
import base64
import datetime
import urllib.parse
import requests
import bcrypt
import jwt

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

KST = datetime.timezone(datetime.timedelta(hours=9))

class NaverCommerceAPI:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.last_error = None
        self.reload_config()

    def reload_config(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        except Exception:
            self.config = {}
            
        self.client_id = os.environ.get("NAVER_CLIENT_ID", self.config.get("client_id", "")).strip()
        self.client_secret = os.environ.get("NAVER_CLIENT_SECRET", self.config.get("client_secret", "")).strip()
        self.base_url = "https://api.commerce.naver.com/external"
        self.access_token = None
        self.token_expires_at = 0

    def generate_client_secret_sign(self, timestamp):
        """Naver Commerce API client_secret_sign using bcrypt or PyJWT"""
        if not self.client_id or not self.client_secret or "YOUR_CLIENT" in self.client_id:
            return None

        password = f"{self.client_id}_{timestamp}"
        try:
            if self.client_secret.startswith("$2a$") or self.client_secret.startswith("$2b$"):
                hashed = bcrypt.hashpw(password.encode('utf-8'), self.client_secret.encode('utf-8'))
                return base64.b64encode(hashed).decode('utf-8')
            else:
                try:
                    hashed = bcrypt.hashpw(password.encode('utf-8'), self.client_secret.encode('utf-8'))
                    return base64.b64encode(hashed).decode('utf-8')
                except ValueError:
                    payload = {"iss": self.client_id, "timestamp": timestamp}
                    return jwt.encode(payload, self.client_secret, algorithm="HS256")
        except Exception as e:
            print(f"[NaverAPI Signature Error] {e}")
            return None

    def get_access_token(self):
        """OAuth2 token request with detailed error reporting"""
        self.reload_config()
        self.last_error = None

        if not self.client_id or "YOUR_CLIENT" in self.client_id:
            self.last_error = "config.json 파일 또는 환경 변수에 Client ID와 Client Secret을 입력해 주세요."
            return None

        now = time.time()
        if self.access_token and now < self.token_expires_at:
            return self.access_token

        timestamp = int(now * 1000)
        client_secret_sign = self.generate_client_secret_sign(timestamp)
        if not client_secret_sign:
            self.last_error = "API 서명(Signature) 생성에 실패했습니다. Client Secret을 확인해 주세요."
            return None

        url = f"{self.base_url}/v1/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": self.client_id,
            "timestamp": timestamp,
            "grant_type": "client_credentials",
            "type": "SELF",
            "client_secret_sign": client_secret_sign
        }

        try:
            resp = requests.post(url, headers=headers, data=data, timeout=10)
            if resp.status_code == 200:
                res_data = resp.json()
                self.access_token = res_data.get("access_token")
                expires_in = res_data.get("expires_in", 3600)
                self.token_expires_at = now + expires_in - 60
                return self.access_token
            else:
                err_text = resp.text
                if "GW.IP_NOT_ALLOWED" in err_text or resp.status_code == 403:
                    try:
                        curr_ip = requests.get("https://api.ipify.org", timeout=3).text.strip()
                    except Exception:
                        curr_ip = "현재 서버 IP"
                    self.last_error = f"⚠️ [IP 미등록 오류] 현재 서버 IP({curr_ip})가 네이버 커머스 API 센터에 등록되어 있지 않습니다. 네이버 커머스 API 센터 ➔ 내 애플리케이션 ➔ API 호출 IP에 '{curr_ip}'를 추가해 주세요!"
                else:
                    self.last_error = f"네이버 API 로그인 오류 ({resp.status_code}): {err_text}"
                print(f"[NaverAPI Token Error] {self.last_error}")
                return None
        except Exception as e:
            self.last_error = f"네이버 API 네트워크 오류: {str(e)}"
            print(f"[NaverAPI Exception] {e}")
            return None

    def fetch_product_orders(self, days=30):
        """
        Fetches changed product orders for past `days`.
        Chunks into 24-hour windows with 0.15s delay & auto-retry on 429 rate limit.
        Uses KST (UTC+9) timezone to prevent timestamp discrepancies on UTC servers.
        """
        token = self.get_access_token()
        if not token:
            return None

        now = datetime.datetime.now(KST)
        all_statuses = []

        for day_offset in range(days):
            end_time = now - datetime.timedelta(days=day_offset)
            start_time = end_time - datetime.timedelta(days=1)

            last_changed_from = start_time.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")
            last_changed_to = end_time.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")

            url = f"{self.base_url}/v1/pay-order/seller/product-orders/last-changed-statuses"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            params = {
                "lastChangedFrom": last_changed_from,
                "lastChangedTo": last_changed_to
            }

            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code == 429:
                    time.sleep(0.5)
                    resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code == 429:
                    time.sleep(1.0)
                    resp = requests.get(url, headers=headers, params=params, timeout=10)

                if resp.status_code == 200:
                    res_json = resp.json()
                    data = res_json.get("data", {})
                    statuses = []
                    if isinstance(data, list):
                        statuses = data
                    elif isinstance(data, dict):
                        statuses = data.get("lastChangeStatuses", data.get("content", data.get("lastChangedStatuses", [])))
                    
                    if isinstance(statuses, list):
                        all_statuses.extend(statuses)
                else:
                    print(f"[NaverAPI Error] Chunk day -{day_offset} failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                print(f"[NaverAPI Exception] {e}")

            time.sleep(0.15)

        return {"data": {"lastChangeStatuses": all_statuses}}

    def query_order_details(self, product_order_ids):
        """Get detailed order info by product_order_ids"""
        token = self.get_access_token()
        if not token or not product_order_ids:
            return None

        unique_ids = list(set(product_order_ids))
        all_details = []

        for i in range(0, len(unique_ids), 100):
            batch_ids = unique_ids[i:i+100]
            url = f"{self.base_url}/v1/pay-order/seller/product-orders/query"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            data = {
                "productOrderIds": batch_ids
            }

            try:
                resp = requests.post(url, headers=headers, json=data, timeout=10)
                if resp.status_code == 429:
                    time.sleep(0.5)
                    resp = requests.post(url, headers=headers, json=data, timeout=10)

                if resp.status_code == 200:
                    res_json = resp.json()
                    data_res = res_json.get("data", [])
                    if isinstance(data_res, list):
                        all_details.extend(data_res)
                    elif isinstance(data_res, dict):
                        all_details.extend(data_res.get("productOrders", data_res.get("content", [])))
                else:
                    print(f"[NaverAPI Error] Query order details batch failed ({resp.status_code}): {resp.text}")
            except Exception as e:
                print(f"[NaverAPI Exception] {e}")

        return {"data": all_details}

def extract_product_order_ids(raw_orders, status_filter="PAYED"):
    if not isinstance(raw_orders, dict):
        return []
    
    data = raw_orders.get("data", {})
    items = []
    
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("lastChangeStatuses", data.get("content", data.get("lastChangedStatuses", [])))

    status_filter = status_filter.upper()
    
    # 네이버 커머스 API 특성:
    # '신규주문(결제완료)'과 '발주확인(상품준비중)'은 둘 다 productOrderStatus == 'PAYED'입니다.
    # 발주확인 여부(placeOrderStatus == 'OK')는 상품 주문 상세(query_order_details)에서 조회되므로,
    # PAYED 및 PREPARING 탭 모두 결제완료 주문번호를 조회 대상으로 포함합니다.
    if status_filter in ["PAYED", "PREPARING"]:
        target_statuses = ["PAYED", "PAYMENT_WAITING", "PREPARING", "PLACE", "DISPATCHED"]
    elif status_filter == "DELIVERED":
        target_statuses = ["DELIVERED", "DELIVERING", "DELIVERY_COMPLETED", "DISPATCHED"]
    elif status_filter == "PURCHASE_DECIDED":
        target_statuses = ["PURCHASE_DECIDED"]
    else:  # ALL
        target_statuses = []

    product_order_ids = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                st_changed = item.get("lastChangedType", "").upper()
                st_order = item.get("productOrderStatus", "").upper()
                
                is_match = False
                if status_filter == "ALL":
                    is_match = True
                elif status_filter == "DELIVERED":
                    if st_order in target_statuses or (st_changed in target_statuses and st_order != "PURCHASE_DECIDED") or st_order == "DELIVERED":
                        is_match = True
                else:
                    if st_order in target_statuses or st_changed in target_statuses:
                        is_match = True

                if is_match and "productOrderId" in item:
                    product_order_ids.append(item["productOrderId"])
            elif isinstance(item, str):
                product_order_ids.append(item)
                
    return list(set(product_order_ids))

def extract_orders_list(orders_detail, status_filter="PAYED"):
    if not isinstance(orders_detail, dict):
        return []
        
    data = orders_detail.get("data", [])
    raw_list = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("productOrders", data.get("content", []))

    status_filter = status_filter.upper()
    if status_filter == "ALL":
        return raw_list

    filtered_list = []
    for item in raw_list:
        if isinstance(item, dict):
            prod_order = item.get("productOrder", item)
            st_order = prod_order.get("productOrderStatus", "").upper()
            st_changed = prod_order.get("lastChangedType", "").upper()
            place_order_status = str(prod_order.get("placeOrderStatus", "")).upper()

            is_match = False
            if status_filter == "PAYED":
                # 신규주문 (결제완료, 아직 발주 미확인 상태: placeOrderStatus != 'OK')
                if (st_order in ["PAYED", "PAYMENT_WAITING"] or st_changed in ["PAYED", "PAYMENT_WAITING"]) and place_order_status != "OK":
                    is_match = True
            elif status_filter == "PREPARING":
                # 발주확인 (판매자가 스마트스토어에서 발주확인 완료하여 상품준비중인 상태):
                # 결제완료(PAYED) 상태에서 placeOrderStatus가 'OK'인 주문 (배송완료나 구매확정으로 넘어간 주문 제외)
                if (st_order in ["PAYED", "PREPARING", "PLACE"] and place_order_status == "OK") or st_order in ["PREPARING", "PLACE"]:
                    is_match = True
            elif status_filter == "DELIVERED":
                target_statuses = ["DELIVERED", "DELIVERING", "DELIVERY_COMPLETED", "DISPATCHED"]
                if st_order in target_statuses or (st_changed in target_statuses and st_order != "PURCHASE_DECIDED") or st_order == "DELIVERED":
                    is_match = True
            elif status_filter == "PURCHASE_DECIDED":
                if st_order == "PURCHASE_DECIDED" or st_changed == "PURCHASE_DECIDED":
                    is_match = True

            if is_match:
                filtered_list.append(item)
        else:
            filtered_list.append(item)

    return filtered_list

def get_mock_orders(status_filter="PAYED"):
    status_filter = status_filter.upper()
    
    mock_db = {
        "PAYED": [
            {
                "productOrderId": "2026072589012341",
                "orderId": "2026072512345671",
                "productOrderStatus": "PAYED",
                "placeOrderStatus": "NOT_YET",
                "paymentAmount": 425000,
                "settlementAmount": 403750,
                "productName": "엥게이지 커플링 18K 14K 금반지 우정 애끼 민자 이니셜 실반지 선물 / 18K 5푼(1.875 g) / 24호이하 / 유광 / 옐로골드",
                "engravingContent": "KHR",
                "engravingFont": "Annie Use Your Telescope",
                "totalQuantity": 1,
                "optionItems": [
                    "1. 기타메모 (없으면 '없음' 입력): KHR / 사이즈 (호수): 16호 / 각인유무 및 글씨체 선택(각인내용은 기타메모): Annie Use Your Telescope",
                    "2. 중량 (미선택시 1푼): 18K 5푼(1.875 g) / 24호이하",
                    "3. 유광/무광 (미선택시 유광): 유광",
                    "4. 컬러 (미선택시 옐로골드): 옐로골드"
                ],
                "recipientName": "김혜란",
                "recipientPhone": "010-2827-5312",
                "zipCode": "50424",
                "baseAddress": "경상남도 밀양시 내이신촌1길 17 (내이동, 쌍용 더 플래티넘 밀양)",
                "detailAddress": "101동 1001호",
                "shippingDeadline": "7/24 (수요일)까지",
                "specialNotes": ""
            }
        ],
        "PREPARING": [
            {
                "productOrderId": "2026072489012342",
                "orderId": "2026072412345672",
                "productOrderStatus": "PAYED",
                "placeOrderStatus": "OK",
                "paymentAmount": 820000,
                "settlementAmount": 779000,
                "productName": "14K 데일리 가드링 **유광**",
                "engravingContent": "Love",
                "engravingFont": "나눔명조",
                "totalQuantity": 1,
                "optionItems": ["0.5돈 12호"],
                "recipientName": "김민서",
                "recipientPhone": "010-1234-5678",
                "zipCode": "06123",
                "baseAddress": "서울특별시 강남구 테헤란로 123",
                "detailAddress": "5층 501호",
                "shippingDeadline": "7/26 (일요일)까지",
                "specialNotes": "빠른 제작 요청"
            }
        ],
        "DELIVERED": [
            {
                "productOrderId": "2026072089012343",
                "orderId": "2026072012345673",
                "productOrderStatus": "DELIVERED",
                "paymentAmount": 425000,
                "settlementAmount": 403750,
                "productName": "엥게이지 커플링 18K 14K 금반지 / 18K 5푼(1.875 g) / 옐로골드",
                "engravingContent": "KHR",
                "engravingFont": "Annie Use Your Telescope",
                "totalQuantity": 1,
                "optionItems": [
                    "1. 기타메모: KHR / 사이즈 (호수): 16호 / 각인유무: Annie Use Your Telescope",
                    "2. 중량: 18K 5푼(1.875 g)",
                    "3. 유광/무광: 유광",
                    "4. 컬러: 옐로골드"
                ],
                "recipientName": "김혜란",
                "recipientPhone": "010-2827-5312",
                "zipCode": "50424",
                "baseAddress": "경상남도 밀양시 내이신촌1길 17 (내이동, 쌍용 더 플래티넘 밀양)",
                "detailAddress": "101동 1001호",
                "shippingDeadline": "7/24 (수요일)까지",
                "specialNotes": ""
            }
        ],
        "PURCHASE_DECIDED": [
            {
                "productOrderId": "2026071589012344",
                "orderId": "2026071512345674",
                "productOrderStatus": "PURCHASE_DECIDED",
                "paymentAmount": 1200000,
                "settlementAmount": 1140000,
                "productName": "18K 커플링 세트",
                "engravingContent": "Forever",
                "engravingFont": "나눔고딕",
                "totalQuantity": 1,
                "optionItems": ["2돈 세트"],
                "recipientName": "이하은",
                "recipientPhone": "010-5555-7777",
                "zipCode": "03111",
                "baseAddress": "서울특별시 종로구 종로 100",
                "detailAddress": "301호",
                "shippingDeadline": "7/18 (토요일)까지",
                "specialNotes": "선물용 포장"
            }
        ]
    }

    if status_filter == "ALL":
        return mock_db["PAYED"] + mock_db["PREPARING"] + mock_db["DELIVERED"] + mock_db["PURCHASE_DECIDED"]
    
    return mock_db.get(status_filter, mock_db["PAYED"])
