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

def is_active_schedule():
    """상시 24시간 감시 (날짜/시간 제한 없음)"""
    return True, "상시 24시간 가동 중 (제한 없음)"

# 텔레그램 봇 설정 (환경 변수 우선, 기본값 탑재)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8886172557:AAHdRasA0I-wQY1qITtAGm-M7Zfk01xI2_Y")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8284334133")

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
    """유튜브 최신 영상 및 쇼츠 통합 감지 (공식 API + HTML 크롤링)"""
    videos = []
    seen_in_fetch = set()
    
    # 1. YouTube Data API v3 사용 (재생목록 최우선 조회)
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
                    title = snippet.get("title", "새 유튜브 영상")
                    published = snippet.get("publishedAt", "실시간 감지")
                    
                    if v_id and v_id not in seen_in_fetch:
                        seen_in_fetch.add(v_id)
                        videos.append({
                            "id": v_id,
                            "title": title,
                            "link": f"https://www.youtube.com/watch?v={v_id}",
                            "published": published
                        })
        except Exception as e:
            logging.error(f"유튜브 API v3 호출 실패: {e}")

    # 2. /shorts 및 /videos HTML 직접 교차 크롤링 (쇼츠 전용 탭 100% 탐지)
    ts = int(time.time() * 1000)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache, no-store, max-age=0, must-revalidate",
        "Pragma": "no-cache"
    }

    channel_target = CHANNEL_HANDLE if CHANNEL_HANDLE.startswith("@") else f"channel/{CHANNEL_ID}"
    
    for path in ["/shorts", "/videos"]:
        try:
            url = f"https://www.youtube.com/{channel_target}{path}?t={ts}&nocache={ts}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=4) as response:
                html = response.read().decode("utf-8")
            
            video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)))
            for v_id in video_ids:
                if v_id not in seen_in_fetch:
                    seen_in_fetch.add(v_id)
                    
                    title = "새 유튜브 영상"
                    pos = html.find(f'"videoId":"{v_id}"')
                    if pos != -1:
                        snippet = html[pos:pos+1200]
                        t_match = re.search(r'"text":"([^"]+)"', snippet) or re.search(r'"simpleText":"([^"]+)"', snippet)
                        if t_match:
                            try:
                                title = t_match.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
                            except Exception:
                                title = t_match.group(1)
                    
                    link = f"https://www.youtube.com/shorts/{v_id}" if path == "/shorts" else f"https://www.youtube.com/watch?v={v_id}"
                    videos.append({
                        "id": v_id,
                        "title": title,
                        "link": link,
                        "published": "초단위 실시간 감지"
                    })
        except Exception as e:
            logging.error(f"유튜브 HTML {path} 스크래핑 에러: {e}")

    return videos

def monitor_loop():
    """스케줄 기반 유튜브 감시 메인 루프"""
    global seen_video_ids
    
    # 봇 가동 시 이전 채널이나 삭제된 영상의 잔재 ID를 제거하기 위해 집합 초기화
    seen_video_ids = set()
    
    logging.info(f"🚀 스케줄 기반 유튜브 감시 루프 시작 (가동시간: 10:00~18:00 KST, 주기: {CHECK_INTERVAL}초)")
    
    # 가동 초기화: 현재 채널에 실제 존재하는 최신 영상 ID를 불러와 등록
    try:
        initial_videos = fetch_latest_videos()
        for v in initial_videos:
            seen_video_ids.add(v["id"])
        save_seen_videos()
        
        start_msg = (
            f"🤖 [업비트 유튜브 감시 봇 실시간 가동 시작]\n"
            f"⏰ 운영 스케줄: 24시간 상시 감시 중 (날짜/시간 제한 없음)\n"
            f"📌 감시 채널: {CHANNEL_HANDLE} (업비트 공식 채널)\n"
            f"✅ 업비트 기존 영상 {len(seen_video_ids)}개 등록 완료. (지금부터 새로 올라오는 일반 영상 및 쇼츠 즉시 알림)"
        )
        send_telegram_message(start_msg)
    except Exception as e:
        logging.error(f"초기 영상 목록 설정 에러: {e}")

    while True:
        try:
            is_active, reason = is_active_schedule()
            
            if is_active:
                videos = fetch_latest_videos()
                for v in videos:
                    v_id = v["id"]
                    if v_id not in seen_video_ids:
                        logging.info(f"🚨 새 영상 감지!: {v['title']} ({v['link']})")
                        
                        msg = (
                            f"🚨 [업비트 새 영상 등록 알림]\n\n"
                            f"📌 제목: {v['title']}\n"
                            f"🔗 링크: {v['link']}\n"
                            f"⏰ 게시 시간: {v['published']}"
                        )
                        
                        send_telegram_message(msg)
                        seen_video_ids.add(v_id)
                        save_seen_videos()
                
                time.sleep(CHECK_INTERVAL)
            else:
                # 10:00~18:00 가동 시간이 아닐 때는 유튜브 API 호출을 전혀 하지 않고 30초 간격 대기
                logging.info(f"⏸️ [스케줄 대기 - API 호출 중단] {reason}")
                time.sleep(30)
            
        except Exception as e:
            logging.error(f"감시 루프 중 에러: {e}")
            time.sleep(CHECK_INTERVAL)

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