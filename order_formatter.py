import re
import datetime

def format_currency(val):
    if val is None or val == "":
        return ""
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)

def format_shipping_deadline(date_str_or_dt):
    if not date_str_or_dt:
        return ""
    
    if "까지" in str(date_str_or_dt) or "요일" in str(date_str_or_dt):
        return str(date_str_or_dt)
        
    try:
        clean_str = str(date_str_or_dt).replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(clean_str)
        weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        day_of_week = weekdays[dt.weekday()]
        return f"{dt.month}/{dt.day} ({day_of_week})까지"
    except Exception:
        return str(date_str_or_dt)

def parse_weight_value(w_str):
    """Converts weight string into relative numerical score for sorting (1돈=10.0, 1푼=1.0)"""
    if not w_str:
        return 0.0
    m_don = re.search(r'(\d+(?:\.\d+)?)\s*돈', str(w_str))
    if m_don:
        return float(m_don.group(1)) * 10.0
    m_pun = re.search(r'(\d+(?:\.\d+)?)\s*푼', str(w_str))
    if m_pun:
        return float(m_pun.group(1)) * 1.0
    m_g = re.search(r'(\d+(?:\.\d+)?)\s*g', str(w_str))
    if m_g:
        return float(m_g.group(1)) * 2.666
    return 0.0

def parse_size_value(s_str):
    """Extracts numerical ring size for sorting (e.g. '17호' -> 17.0, '12.5호' -> 12.5)"""
    if not s_str:
        return 0.0
    m = re.search(r'(\d+(?:\.\d+)?)', str(s_str))
    return float(m.group(1)) if m else 0.0

def parse_item_details(item):
    """
    Parses a single raw order item or dictionary into structured jewelry fields.
    """
    raw_prod_name = item.get("productName", "")
    options = item.get("optionItems", [])
    if isinstance(options, str):
        options = [options]

    value_parts = []
    for opt in options:
        opt_str = str(opt)
        if ":" in opt_str:
            val = opt_str.split(":", 1)[1].strip()
            value_parts.append(val)
        else:
            value_parts.append(opt_str)

    value_text = " ".join(value_parts)
    full_text = raw_prod_name + " " + " ".join(options)
    
    # 1. Gold Karat
    karat = ""
    if "18K" in full_text or "18k" in full_text:
        karat = "18K"
    elif "14K" in full_text or "14k" in full_text:
        karat = "14K"
    elif "24K" in full_text or "24k" in full_text or "순금" in full_text:
        karat = "24K"

    # 2. Weights found
    weights_found = []
    for w in re.findall(r'(\d+(?:\.\d+)?\s*(?:푼|돈))', value_text):
        w_clean = w.replace(" ", "")
        if w_clean not in weights_found:
            weights_found.append(w_clean)
    if not weights_found:
        for w in re.findall(r'(\d+(?:\.\d+)?\s*(?:푼|돈))', full_text):
            w_clean = w.replace(" ", "")
            if w_clean not in weights_found:
                weights_found.append(w_clean)

    weight = weights_found[0] if weights_found else ""

    # 3. Product Type
    product_type = "평반지"
    if weight == "1푼" or "1푼" in value_text:
        product_type = "실반지"
    elif "평반지" in raw_prod_name or "엥게이지" in raw_prod_name:
        product_type = "평반지"
    elif "가드링" in raw_prod_name:
        product_type = "가드링"
    elif "팔찌" in raw_prod_name:
        product_type = "팔찌"
    elif "목걸이" in raw_prod_name:
        product_type = "목걸이"
    elif "반지" in raw_prod_name:
        product_type = "반지"

    # 4. Color
    color = "옐로골드"
    if "핑크골드" in value_text or "로즈골드" in value_text or "핑크" in value_text:
        color = "**핑크골드**"
    elif "화이트골드" in value_text or "화이트" in value_text:
        color = "**화이트골드**"
    elif "옐로골드" in value_text or "옐로우골드" in value_text or "옐로우" in value_text:
        color = "옐로골드"

    # 5. Luster
    luster = ""
    if "무광" in value_text and "유광" not in value_text:
        luster = "**무광**"
    elif "무광" in value_text and "유광" in value_text:
        for val in value_parts:
            if "무광" in val and "유광" not in val:
                luster = "**무광**"
                break

    # 6. Sizes found (supports integers like 13호, decimals like 12.5호, multiple sizes like 13호, 17호)
    sizes_found = []
    for opt_str in options:
        matches = re.findall(r'(\d+(?:\.\d+)?\s*호)(?!\s*이하|\s*이상)', str(opt_str))
        for s in matches:
            s_val = s.replace(" ", "")
            if s_val not in sizes_found:
                sizes_found.append(s_val)

    if not sizes_found:
        all_matches = re.findall(r'(\d+(?:\.\d+)?\s*호)(?!\s*이하|\s*이상)', full_text)
        for s in all_matches:
            s_val = s.replace(" ", "")
            if s_val not in sizes_found:
                sizes_found.append(s_val)

    # 7. Engraving
    raw_memo = item.get("engravingContent", "").strip()
    raw_font = item.get("engravingFont", "").strip()

    for opt in options:
        opt_str = str(opt)
        if "기타메모" in opt_str or "각인" in opt_str:
            m_memo = re.search(r'기타메모[^\:]*:\s*([^/]+)', opt_str)
            if m_memo and not raw_memo:
                val = m_memo.group(1).strip()
                if val not in ["없음", "없음 입력", "각인안함", "none", "None", "-", "."]:
                    raw_memo = val

            m_font = re.search(r'글씨체[^\:]*:\s*([^/]+)', opt_str)
            if m_font and not raw_font:
                val = m_font.group(1).strip()
                if val not in ["없음", "선택안함", "각인안함", "none", "None", "-", "."]:
                    raw_font = val

    if raw_memo in ["없음", "없음 입력", "각인안함", "none", "None", "-", "."]:
        raw_memo = ""
    if raw_font in ["없음", "선택안함", "각인안함", "none", "None", "-", "."]:
        raw_font = ""

    return {
        "karat": karat,
        "product_type": product_type,
        "weight": weight,
        "weights": weights_found,
        "color": color,
        "luster": luster,
        "sizes": sizes_found,
        "engraving_content": raw_memo,
        "engraving_font": raw_font,
        "options": options,
        "raw_prod_name": raw_prod_name
    }

def group_orders_by_order_id(raw_orders_list):
    if not raw_orders_list:
        return []

    grouped = {}
    
    for item in raw_orders_list:
        if not isinstance(item, dict):
            continue

        order_info = item.get("order", {})
        prod_order = item.get("productOrder", {})
        
        if "productOrderId" in item and "orderId" in item and "productName" in item:
            master_order_id = item.get("orderId", item.get("productOrderId"))
            order_data = item
        else:
            master_order_id = order_info.get("orderId") or prod_order.get("orderId") or prod_order.get("productOrderId")
            order_data = item

        if not master_order_id:
            master_order_id = f"UNKNOWN_{len(grouped)}"

        if master_order_id not in grouped:
            grouped[master_order_id] = []
        grouped[master_order_id].append(order_data)

    merged_orders = []
    for order_id, items in grouped.items():
        if not items:
            continue

        first_item = items[0]
        
        # Mock objects
        if "productOrderId" in first_item and "productName" in first_item and isinstance(first_item.get("optionItems"), list):
            total_pay = sum(it.get("paymentAmount", 0) for it in items)
            total_settle = sum(it.get("settlementAmount", 0) for it in items)
            total_qty = sum(it.get("totalQuantity", 1) for it in items)
            
            all_options = []
            for it in items:
                for opt in it.get("optionItems", []):
                    if opt and opt not in all_options:
                        all_options.append(opt)

            merged_item = dict(first_item)
            merged_item["paymentAmount"] = total_pay
            merged_item["settlementAmount"] = total_settle
            merged_item["totalQuantity"] = total_qty
            merged_item["optionItems"] = all_options
            merged_item["subItems"] = items
            merged_orders.append(merged_item)
            continue

        # Raw Naver Commerce API objects
        total_payment = 0
        total_settlement = 0
        total_qty = 0
        option_list = []
        
        product_names = []
        sub_items_list = []

        for it in items:
            po = it.get("productOrder", {})
            
            pay_amt = po.get("totalPaymentAmount", po.get("unitPrice", 0) * po.get("quantity", 1))
            settle_amt = po.get("expectedSettlementAmount", int(pay_amt * 0.95))
            qty = po.get("quantity", 1)
            
            total_payment += pay_amt
            total_settlement += settle_amt
            total_qty += qty

            p_name = po.get("productName", "")
            if p_name and p_name not in product_names:
                product_names.append(p_name)
                
            opt_code = po.get("optionCode", po.get("productOption", ""))
            if opt_code and opt_code not in option_list:
                option_list.append(opt_code)

            shipping_addr = po.get("shippingAddress", {})
            shipping_deadline = format_shipping_deadline(po.get("shippingDueDate", ""))
            shipping_memo = po.get("shippingMemo", po.get("deliveryMemo", ""))

            sub_items_list.append({
                "productOrderId": po.get("productOrderId"),
                "productName": p_name,
                "optionItems": [opt_code] if opt_code else [],
                "quantity": qty,
                "paymentAmount": pay_amt,
                "settlementAmount": settle_amt,
                "recipientName": shipping_addr.get("name", ""),
                "recipientPhone": shipping_addr.get("tel1", shipping_addr.get("tel2", "")),
                "baseAddress": shipping_addr.get("baseAddress", ""),
                "detailAddress": shipping_addr.get("detailedAddress", ""),
                "shippingDeadline": shipping_deadline,
                "specialNotes": shipping_memo
            })

        first_po = first_item.get("productOrder", {})
        first_addr = first_po.get("shippingAddress", {})

        merged_orders.append({
            "orderId": order_id,
            "productOrderId": first_po.get("productOrderId", order_id),
            "productOrderStatus": first_po.get("productOrderStatus", first_po.get("lastChangedType", "")),
            "placeOrderStatus": first_po.get("placeOrderStatus", ""),
            "paymentAmount": total_payment,
            "settlementAmount": total_settlement,
            "margin": None,
            "productName": " / ".join(product_names) if product_names else "상품",
            "totalQuantity": total_qty,
            "optionItems": option_list,
            "recipientName": first_addr.get("name", ""),
            "recipientPhone": first_addr.get("tel1", first_addr.get("tel2", "")),
            "zipCode": first_addr.get("zipCode", ""),
            "baseAddress": first_addr.get("baseAddress", ""),
            "detailAddress": first_addr.get("detailedAddress", ""),
            "shippingDeadline": format_shipping_deadline(first_po.get("shippingDueDate", "")),
            "specialNotes": first_po.get("shippingMemo", first_po.get("deliveryMemo", "")),
            "subItems": sub_items_list
        })

    return merged_orders

def format_order_to_text(order_item):
    pay_amt = format_currency(order_item.get("paymentAmount"))
    settle_amt = format_currency(order_item.get("settlementAmount"))

    sub_items = order_item.get("subItems", [])
    parsed_main = parse_item_details(order_item)

    # 1. Collect size items and weight items with quantity expansion
    size_entries = []
    weight_entries = []

    if sub_items:
        for sub in sub_items:
            parsed_sub = parse_item_details(sub)
            qty = max(1, int(sub.get("quantity", 1)))

            # Collect sizes
            sub_sizes = parsed_sub.get("sizes", [])
            if sub_sizes:
                if len(sub_sizes) == 1:
                    for _ in range(qty):
                        size_entries.append({
                            "size": sub_sizes[0],
                            "engraving_content": parsed_sub["engraving_content"],
                            "engraving_font": parsed_sub["engraving_font"],
                            "sub": sub
                        })
                else:
                    for sz in sub_sizes:
                        size_entries.append({
                            "size": sz,
                            "engraving_content": parsed_sub["engraving_content"],
                            "engraving_font": parsed_sub["engraving_font"],
                            "sub": sub
                        })

            # Collect weights
            sub_weights = parsed_sub.get("weights", [])
            if not sub_weights and parsed_sub.get("weight"):
                sub_weights = [parsed_sub["weight"]]

            if sub_weights:
                if len(sub_weights) == 1:
                    for _ in range(qty):
                        weight_entries.append(sub_weights[0])
                else:
                    for w in sub_weights:
                        weight_entries.append(w)

    # Fallback if no sub_items or sizes not found in sub_items
    if not size_entries:
        main_sizes = parsed_main.get("sizes", [])
        total_q = max(1, int(order_item.get("totalQuantity") or order_item.get("quantity") or 1))
        if len(main_sizes) == 1:
            for _ in range(total_q):
                size_entries.append({
                    "size": main_sizes[0],
                    "engraving_content": parsed_main["engraving_content"],
                    "engraving_font": parsed_main["engraving_font"],
                    "sub": order_item
                })
        elif len(main_sizes) > 1:
            for sz in main_sizes:
                size_entries.append({
                    "size": sz,
                    "engraving_content": parsed_main["engraving_content"],
                    "engraving_font": parsed_main["engraving_font"],
                    "sub": order_item
                })
        else:
            for _ in range(total_q):
                size_entries.append({
                    "size": "",
                    "engraving_content": parsed_main["engraving_content"],
                    "engraving_font": parsed_main["engraving_font"],
                    "sub": order_item
                })

    if not weight_entries:
        main_weights = parsed_main.get("weights", [])
        if not main_weights and parsed_main.get("weight"):
            main_weights = [parsed_main["weight"]]
        total_q = max(1, len(size_entries))
        if len(main_weights) == 1:
            for _ in range(total_q):
                weight_entries.append(main_weights[0])
        elif len(main_weights) > 1:
            for w in main_weights:
                weight_entries.append(w)
        else:
            for _ in range(total_q):
                weight_entries.append("")

    # 2. Sort sizes and weights ASCENDING so smaller weight pairs with smaller size, and larger weight pairs with larger size
    # E.g. 8푼 <-> 13호, 1돈 <-> 17호 (작은 호수에 가벼운 중량, 큰 호수에 무거운 중량 매칭)
    size_entries.sort(key=lambda x: parse_size_value(x["size"]))
    weight_entries.sort(key=lambda w: parse_weight_value(w))

    # 3. Match sizes with weights
    ring_entries = []
    default_weight = weight_entries[0] if weight_entries else parsed_main["weight"]
    default_rec = order_item.get("recipientName", "")
    default_phone = order_item.get("recipientPhone", "")
    default_base = order_item.get("baseAddress", "")
    default_detail = order_item.get("detailAddress", "")
    default_addr = f"{default_base}, {default_detail}".strip(", ")
    default_deadline = order_item.get("shippingDeadline", "")

    for i, s_ent in enumerate(size_entries):
        sub = s_ent.get("sub", order_item)
        w = weight_entries[i] if i < len(weight_entries) else default_weight
        sz = s_ent["size"]
        memo = s_ent["engraving_content"] or parsed_main["engraving_content"]
        font = s_ent["engraving_font"] or parsed_main["engraving_font"]

        sub_rec = sub.get("recipientName") or default_rec
        sub_phone = sub.get("recipientPhone") or default_phone
        sub_base = sub.get("baseAddress") or default_base
        sub_detail = sub.get("detailAddress") or default_detail
        sub_addr = f"{sub_base}, {sub_detail}".strip(", ") or default_addr
        sub_deadline = sub.get("shippingDeadline") or default_deadline

        ring_entries.append({
            "weight": w,
            "size": sz,
            "engraving_content": memo,
            "engraving_font": font,
            "recipient": sub_rec,
            "phone": sub_phone,
            "address": sub_addr,
            "deadline": sub_deadline
        })

    # Common traits
    karat = parsed_main["karat"]
    prod_type = parsed_main["product_type"]
    color = parsed_main["color"]
    luster = parsed_main["luster"]

    # Check if all ring entries are identical (same weight, same size, same engraving)
    all_identical = False
    if len(ring_entries) > 1:
        first_r = ring_entries[0]
        all_identical = all(
            r["size"] == first_r["size"] and
            r["weight"] == first_r["weight"] and
            r["engraving_content"] == first_r["engraving_content"] and
            r["engraving_font"] == first_r["engraving_font"]
            for r in ring_entries
        )

    # If all items are identical (e.g. 18호 1돈 2개): format as single item with '수량 : N개'
    # If items are different (e.g. 13호 8푼, 17호 1돈): format as multi item list (1. 8푼 13호, 2. 1돈 17호)
    is_multi = (len(ring_entries) > 1) and not all_identical

    lines = [
        "[주문정보]",
        f"결제금액 : {pay_amt}",
        f"정산예정금액 : {settle_amt}",
        f"예상마진  : ",
        ""
    ]

    if not is_multi:
        entry = ring_entries[0] if ring_entries else {
            "weight": parsed_main["weight"],
            "size": parsed_main["sizes"][0] if parsed_main["sizes"] else "",
            "engraving_content": parsed_main["engraving_content"],
            "engraving_font": parsed_main["engraving_font"],
            "recipient": default_rec,
            "phone": default_phone,
            "address": default_addr,
            "deadline": default_deadline
        }
        parts = []
        if karat: parts.append(karat)
        if prod_type: parts.append(prod_type)
        if entry["weight"]: parts.append(entry["weight"])
        if entry["size"]: parts.append(entry["size"])
        if color: parts.append(color)
        if luster: parts.append(luster)
        
        prod_text = " ".join(parts) if parts else order_item.get("productName", "")
        lines.append(f"제품 : {prod_text}")

        # If quantity is 2 or more, clearly indicate quantity
        total_q = len(ring_entries)
        if total_q >= 2:
            lines.append(f"수량 : {total_q}개")

        memo = entry["engraving_content"]
        font = entry["engraving_font"]
        if memo and font:
            lines.append(f"각인내용 : {memo}")
            lines.append(f"각인글씨체 : {font}")
        elif memo and not font:
            lines.append("각인없음")
        else:
            lines.append("각인없음")

        lines.extend([
            "",
            f"받는사람 : {entry['recipient']} ({entry['phone']})",
            f"주소 : {entry['address']}",
            f"배송기한 : {entry['deadline']}"
        ])
        
        delivery_memo = order_item.get("specialNotes", "").strip()
        special_notes_list = []
        if delivery_memo:
            special_notes_list.append(delivery_memo)
        if memo and not font:
            special_notes_list.insert(0, memo)
            
        if special_notes_list:
            lines.append(f"특이사항 : {' / '.join(special_notes_list)}")

    else:
        parts = []
        if karat: parts.append(karat)
        if prod_type: parts.append(prod_type)
        if color: parts.append(color)
        if luster: parts.append(luster)
        
        common_prod_text = " ".join(parts) if parts else order_item.get("productName", "")
        lines.append(f"제품 : {common_prod_text}")
        lines.append(f"수량 : {len(ring_entries)}개")

        engravings = [r["engraving_content"] for r in ring_entries]
        fonts = [r["engraving_font"] for r in ring_entries]
        all_same_engraving = len(set(engravings)) == 1
        all_same_font = len(set(fonts)) == 1

        addresses = [r["address"] for r in ring_entries]
        recipients = [r["recipient"] for r in ring_entries]
        all_same_shipping = (len(set(addresses)) == 1) and (len(set(recipients)) == 1)

        for i, entry in enumerate(ring_entries, start=1):
            item_desc = f"{i}. {entry['weight']} {entry['size']}".strip()
            
            if not all_same_engraving or not all_same_font:
                if entry["engraving_content"]:
                    item_desc += f" / 각인내용 : {entry['engraving_content']}"
                else:
                    item_desc += " / 각인없음"

            if not all_same_shipping:
                item_desc += f" / 받는사람 : {entry['recipient']} ({entry['phone']}) / 주소 : {entry['address']}"

            lines.append(item_desc)

        if all_same_engraving and engravings[0] and fonts[0]:
            lines.append(f"각인내용 : {engravings[0]}")
            lines.append(f"각인글씨체 : {fonts[0]}")
        elif all_same_engraving and engravings[0] and not fonts[0]:
            lines.append("각인없음")
        elif all_same_engraving and not engravings[0]:
            lines.append("각인없음")

        if all_same_shipping:
            lines.extend([
                "",
                f"받는사람 : {ring_entries[0]['recipient']} ({ring_entries[0]['phone']})",
                f"주소 : {ring_entries[0]['address']}",
                f"배송기한 : {ring_entries[0]['deadline']}"
            ])

        delivery_memo = order_item.get("specialNotes", "").strip()
        if delivery_memo:
            lines.append(f"특이사항 : {delivery_memo}")

    return "\n".join(lines)
