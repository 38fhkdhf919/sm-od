import os
import re
import time
import json
import logging
import threading
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify
import requests

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# KST (한국 표준시 UTC+9)
KST = timezone(timedelta(hours=9))

# 가동 스케줄 설정 (오늘 7/29부터 8/1까지 4일간: 매일 오전 10시 ~ 오후 6시 KST)
SCHEDULE_START_DATE = datetime(2026, 7, 29, 0, 0, 0, tzinfo=KST)
SCHEDULE_END_DATE = datetime(2026, 8, 1, 23, 59, 59, tzinfo=KST)
ACTIVE_START_HOUR = 10  # 오전 10시
ACTIVE_END_HOUR = 18    # 오후 6시 (18:00 정각 종료)

current_bot_mode = None  # "MONITORING", "IDLE", "EXPIRED"

def get_schedule_status():
    """현재 한국 시각 기준 봇 가동 상태 및 이유 판별"""
    now = datetime.now(KST)
    
    if now < SCHEDULE_START_DATE:
        return "IDLE", "가동 기간 전", f"가동 시작 예정일: {SCHEDULE_START_DATE.strftime('%m월 %d일')} 오전 10시 00분"
    
    if now > SCHEDULE_END_DATE:
        return "EXPIRED", "가동 스케줄 만료", "4일간의 가동 스케줄이 모두 완료되었습니다."
    
    if ACTIVE_START_HOUR <= now.hour < ACTIVE_END_HOUR:
        return "MONITORING", "실시간 감시 가동 중", f"오늘({now.strftime('%m/%d')}) 오후 18시 00분까지 감시 실행"
    else:
        if now.hour >= ACTIVE_END_HOUR:
            next_wake = (now + timedelta(days=1)).strftime("%m월 %d일") + " 오전 10시 00분"
        else:
            next_wake = now.strftime("%m월 %d일") + " 오전 10시 00분"
        return "IDLE", "대기 모드", f"다음 자동 가동 예정 시각: {next_wake}"

def is_active_schedule():
    mode, status_text, detail = get_schedule_status()
    return (mode == "MONITORING"), f"{status_text} ({detail})"

# 텔레그램 봇 및 단톡방/관리자 설정 (환경 변수 우선, 기본값 탑재)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8886172557:AAHdRasA0I-wQY1qITtAGm-M7Zfk01xI2_Y")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-5452529899")  # 텔레그램 단톡방 Chat ID
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID", "8284334133")         # 방장(관리자) 고유 User ID

# 유튜브 API 키 (발급받은 키 - 1~3초 최단시간 즉시 감지)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyCv1dvIBNwOydBORbik16iZWW9c7NG-LCY")

# 감시 대상 유튜브 채널 ID (업비트 공식 채널: @UpbitOfficial / UCnUVXiMdlPmDI9NAnX1AlGQ)
CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "@UpbitOfficial")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "UCnUVXiMdlPmDI9NAnX1AlGQ")
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"

# 감시 주기 (초)
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", 5))

# 이미 처리한 영상 ID 저장용 집합
seen_video_ids = set()
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_videos.json")

def load_seen_videos():
    global seen_video_ids
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                seen_video_ids = set(json.load(f))
                logging.info(f"기존 영상 목록 {len(seen_video_ids)}개 로드 완료")
        except Exception as e:
            logging.error(f"기존 영상 파일 로드 실패: {e}")

def save_seen_videos():
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(list(seen_video_ids), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"영상 파일 저장 실패: {e}")

def send_telegram_message(text):
    """텔레그램 메시지 전송 함수"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            logging.info("텔레그램 알림 전송 성공")
        else:
            logging.error(f"텔레그램 전송 실패 ({res.status_code}): {res.text}")
    except Exception as e:
        logging.error(f"텔레그램 전송 예외 발생: {e}")

def fetch_latest_videos():
    """유튜브 공식 Data API v3 업로드 재생목록 전용 초고속 감지"""
    videos = []
    
    if YOUTUBE_API_KEY:
        try:
            uploads_playlist_id = "UU" + CHANNEL_ID[2:] if CHANNEL_ID.startswith("UC") else CHANNEL_ID
            api_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={uploads_playlist_id}&maxResults=10&key={YOUTUBE_API_KEY}"
            
            req = urllib.request.Request(api_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                for item in res_data.get("items", []):
                    snippet = item.get("snippet", {})
                    v_id = snippet.get("resourceId", {}).get("videoId")
                    title = snippet.get("title", "업비트 새 영상")
                    published = snippet.get("publishedAt", "실시간 감지")
                    
                    if v_id:
                        videos.append({
                            "id": v_id,
                            "title": title,
                            "link": f"https://www.youtube.com/watch?v={v_id}",
                            "published": published
                        })
        except Exception as e:
            logging.error(f"유튜브 API v3 호출 실패: {e}")

    return videos

def telegram_command_listener():
    """텔레그램 단톡방 방장 전용 종료 명령어 수신 스레드 (/off, 종료 명령)"""
    global current_bot_mode
    offset = 0
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = requests.get(url, timeout=12)
            if res.status_code == 200:
                data = res.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message") or update.get("channel_post")
                    if not message:
                        continue
                    
                    text = message.get("text", "").strip().lower()
                    sender_id = str(message.get("from", {}).get("id", ""))
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    
                    # 종료 명령 키워드 검사
                    if text in ["/off", "off", "종료", "끝"]:
                        if sender_id == ADMIN_USER_ID or sender_id == "":
                            now = datetime.now(KST)
                            next_time = (now + timedelta(days=1)).strftime("%m월 %d일") + " 오전 10시 00분"
                            
                            current_bot_mode = "IDLE"
                            msg = (
                                f"⏸️ [방장 명령으로 오늘 감시 종료]\n\n"
                                f"👮‍♂️ 방장님의 이벤트 종료 신호를 받아 대기 모드로 전환합니다.\n"
                                f"⏰ 현재 상태: 대기 모드 (유튜브 API 호출 0회, 쿼터 소모 0)\n"
                                f"⏳ 다음 자동 가동 시각: {next_time}\n"
                                f"📌 감시 채널: {CHANNEL_HANDLE} (업비트 공식 채널)"
                            )
                            send_telegram_message(msg)
                        else:
                            # 일반 단톡방 참가자가 명령어를 쳤을 때
                            if chat_id == TELEGRAM_CHAT_ID:
                                send_telegram_message("⚠️ 오늘 감시 종료 명령어는 방장(관리자)만 실행할 수 있습니다.")
                                
        except Exception as e:
            logging.error(f"텔레그램 명령어 수신 중 에러: {e}")
            
        time.sleep(1)

def monitor_loop():
    """스케줄 기반 유튜브 감시 메인 루프"""
    global seen_video_ids, current_bot_mode
    
    seen_video_ids = set()
    logging.info("🚀 업비트 유튜브 감시 봇 루프 시작 (스케줄: 7/29~8/1 10:00~18:00 KST)")
    
    # 가동 초기화: 현재 업비트 채널에 존재하는 기존 영상 ID 등록
    try:
        initial_videos = fetch_latest_videos()
        for v in initial_videos:
            seen_video_ids.add(v["id"])
        save_seen_videos()
    except Exception as e:
        logging.error(f"초기 영상 목록 설정 에러: {e}")

    while True:
        try:
            mode, status_text, detail = get_schedule_status()
            now = datetime.now(KST)
            
            # 봇 상태 전환 시 텔레그램 알림 즉시 발송
            if mode != current_bot_mode:
                current_bot_mode = mode
                
                if mode == "MONITORING":
                    msg = (
                        f"🟢 [업비트 감시 봇 가동 시작]\n\n"
                        f"⏰ 현재 상태: 유튜브 API 5초 주기 실시간 감시 실행 중\n"
                        f"⏳ 오늘 감시 종료 예정: 오늘({now.strftime('%m/%d')}) 오후 18시 00분까지\n"
                        f"📌 감시 채널: {CHANNEL_HANDLE} (업비트 공식 채널)\n"
                        f"💡 방장님 전용 팁: 오늘 이벤트가 끝났으면 단톡방에 '/off' 또는 '종료'를 입력하세요!\n"
                        f"✅ 기존 영상 {len(seen_video_ids)}개 등록 완료. (유튜브 API 감지 시 즉시 알림)"
                    )
                    send_telegram_message(msg)
                    
                elif mode == "IDLE":
                    next_time = detail.replace("다음 자동 가동 예정 시각: ", "")
                    msg = (
                        f"⏸️ [업비트 감시 봇 대기 모드 전환]\n\n"
                        f"⏰ 현재 상태: 대기 모드 (유튜브 API 호출 0회, 쿼터 소모 0)\n"
                        f"⏳ 다음 자동 가동 시각: {next_time}\n"
                        f"📌 감시 채널: {CHANNEL_HANDLE} (업비트 공식 채널)"
                    )
                    send_telegram_message(msg)
                    
                elif mode == "EXPIRED":
                    msg = (
                        f"🏁 [업비트 감시 봇 스케줄 만료]\n\n"
                        f"📅 지정된 4일간의 가동 스케줄(7/29 ~ 8/1)이 모두 종료되었습니다.\n"
                        f"📌 현재 상태: 대기 모드 유지 중"
                    )
                    send_telegram_message(msg)

            if mode == "MONITORING":
                videos = fetch_latest_videos()
                for v in videos:
                    v_id = v["id"]
                    if v_id not in seen_video_ids:
                        logging.info(f"🚨 유튜브 API 새 영상 감지!: {v['title']} ({v['link']})")
                        
                        msg = (
                            f"🚨 [업비트 새 영상 등록 알림]\n\n"
                            f"📌 제목: {v['title']}\n"
                            f"🔗 링크: {v['link']}\n"
                            f"⏰ 게시 시간: {v['published']}"
                        )
                        
                        send_telegram_message(msg)
                        seen_video_ids.add(v_id)
                        save_seen_videos()
                        
                        # 오늘 새 영상 1개 알림이 전송된 후 자동 대기 모드 전환 안내
                        next_time = (now + timedelta(days=1)).strftime("%m월 %d일") + " 오전 10시 00분"
                        auto_idle_msg = (
                            f"🎉 오늘 새 영상 알림 전송이 완료되었습니다!\n"
                            f"오늘 가동을 자동 종료하고 대기 모드로 들어갑니다.\n"
                            f"⏳ 다음 자동 가동 시각: {next_time}"
                        )
                        send_telegram_message(auto_idle_msg)
                        current_bot_mode = "IDLE"
                        break
                
                time.sleep(CHECK_INTERVAL)
            else:
                # 대기 모드 중에는 API 호출 없이 30초 간격으로 시각만 체크
                time.sleep(30)
            
        except Exception as e:
            logging.error(f"감시 루프 중 에러: {e}")
            time.sleep(CHECK_INTERVAL)

# 백그라운드 명령어 수신 스레드 시작
cmd_thread = threading.Thread(target=telegram_command_listener, daemon=True)
cmd_thread.start()

# Render 배포 및 헬스체크를 위한 Flask 웹 앱
app = Flask(__name__)

@app.route("/")
def home():
    is_active, reason = is_active_schedule()
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    status_html = "<span style='color:green;font-weight:bold;'>🟢 가동 중 (감시 실행 중)</span>" if is_active else "<span style='color:orange;font-weight:bold;'>⏸️ 대기 중 (시간 외)</span>"
    return f"""
    <h2>🤖 업비트 유튜브 감시 봇 모니터링</h2>
    <p><b>한국시간 (KST):</b> {now_kst}</p>
    <p><b>스케줄 가동 상태:</b> {status_html}</p>
    <p><b>상세 이유:</b> {reason}</p>
    <p><b>감시 채널:</b> {CHANNEL_HANDLE}</p>
    <p><b>감시 주기:</b> {CHECK_INTERVAL}초</p>
    """

@app.route("/health")
def health():
    is_active, reason = is_active_schedule()
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    return jsonify({
        "status": "ok",
        "current_kst_time": now_kst,
        "schedule_active": is_active,
        "schedule_reason": reason,
        "monitored_channel": CHANNEL_HANDLE,
        "seen_count": len(seen_video_ids),
        "check_interval": CHECK_INTERVAL
    })

# 백그라운드 감시 스레드 시작
monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)