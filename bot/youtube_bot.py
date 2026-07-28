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

# 가동 스케줄 설정 (내일 7/29부터 8/1까지 4일간: 매일 오전 10시 ~ 오후 6시 KST)
SCHEDULE_START_DATE = datetime(2026, 7, 29, 0, 0, 0, tzinfo=KST)
SCHEDULE_END_DATE = datetime(2026, 8, 1, 23, 59, 59, tzinfo=KST)
ACTIVE_START_HOUR = 10  # 오전 10시
ACTIVE_END_HOUR = 18    # 오후 6시 (18:00 정각 종료)

def is_active_schedule():
    """현재 한국 시간이 지정된 가동 날짜 및 시간대 내에 있는지 검사"""
    now = datetime.now(KST)
    
    # 1. 4일 가동 기간 검사 (2026-07-29 ~ 2026-08-01)
    if now < SCHEDULE_START_DATE:
        return False, "가동 기간 전 (시작 예정: 2026-07-29 오전 10:00 KST)"
    if now > SCHEDULE_END_DATE:
        return False, "가동 4일 기간 종료됨 (종료일: 2026-08-01)"
    
    # 2. 일일 가동 시간대 검사 (10:00 ~ 18:00 KST)
    if ACTIVE_START_HOUR <= now.hour < ACTIVE_END_HOUR:
        return True, f"가동 시간 중 (현재시간 KST {now.strftime('%H:%M:%S')})"
    else:
        return False, f"운영 시간 외 (현재시간 KST {now.strftime('%H:%M')}, 가동시간: 10:00~18:00)"

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
    """유튜브 최신 영상 감지 (공식 API v3 지원 & Anti-Cache 스크래핑 백업)"""
    videos = []
    seen_in_fetch = set()
    
    # 1. YouTube Data API v3 사용 (API 키가 등록되어 있으면 100% 최우선 초고속 감지)
    if YOUTUBE_API_KEY:
        try:
            # 채널의 업로드 전용 재생목록 ID (UC... -> UU...)
            uploads_playlist_id = "UU" + CHANNEL_ID[2:] if CHANNEL_ID.startswith("UC") else CHANNEL_ID
            api_url = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId={uploads_playlist_id}&maxResults=5&key={YOUTUBE_API_KEY}"
            
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
                if videos:
                    return videos
        except Exception as e:
            logging.error(f"유튜브 API v3 호출 실패 (웹 스크래핑으로 전환): {e}")

    # 2. 웹페이지 캐시 우회 스크래핑 (API 키가 없을 때 백업)
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
            f"🤖 [업비트 유튜브 감시 봇 대기 모드 진입]\n"
            f"📅 가동 스케줄: 7/29 ~ 8/1 (4일간, 매일 10:00 ~ 18:00 KST)\n"
            f"📌 감시 채널: {CHANNEL_HANDLE} (업비트 공식 채널)\n"
            f"✅ 업비트 기존 영상 {len(seen_video_ids)}개 등록 완료. (내일 7/29 오전 10시부터 자동 감시가 시작됩니다.)"
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