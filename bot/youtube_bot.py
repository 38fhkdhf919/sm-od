import os
import re
import time
import json
import logging
import threading
import urllib.request
import xml.etree.ElementTree as ET
from flask import Flask, jsonify
import requests

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 텔레그램 봇 설정 (환경 변수 우선, 기본값 탑재)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8886172557:AAHdRasA0I-wQY1qITtAGm-M7Zfk01xI2_Y")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "8284334133")

# 유튜브 API 키 (발급받은 키 - 1~3초 최단시간 즉시 감지)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "AIzaSyCv1dvIBNwOydBORbik16iZWW9c7NG-LCY")

# 감시 대상 유튜브 채널 ID (개인 테스트 채널: @akao11f / UCUaoBr-tZIgdlRtwf4zesmQ)
CHANNEL_HANDLE = os.environ.get("YOUTUBE_CHANNEL_HANDLE", "@akao11f")
CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "UCUaoBr-tZIgdlRtwf4zesmQ")
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
    """5~10초 주기로 유튜브 감시하는 메인 루프"""
    global seen_video_ids
    load_seen_videos()
    
    logging.info(f"🚀 업비트 유튜브 감시 루프 시작 (주기: {CHECK_INTERVAL}초)")
    
    # 첫 실행 시 기존 영상들은 'seen' 처리 (봇 켜지자마자 이전 영상들로 알림 테러 방지)
    initial_videos = fetch_latest_videos()
    if initial_videos and not seen_video_ids:
        for v in initial_videos:
            seen_video_ids.add(v["id"])
        save_seen_videos()
        send_telegram_message(f"🤖 업비트 유튜브 감시 봇 가동 시작!\n현재 최근 영상 ID: {initial_videos[0]['id']}\n제목: {initial_videos[0]['title']}")
    elif seen_video_ids:
        send_telegram_message(f"🤖 업비트 유튜브 감시 봇 재가동되었습니다. (감시 중인 기존 영상 수: {len(seen_video_ids)}개)")

    while True:
        try:
            videos = fetch_latest_videos()
            for v in videos:
                v_id = v["id"]
                if v_id not in seen_video_ids:
                    logging.info(f"🚨 새 영상 감지!: {v['title']} ({v['link']})")
                    
                    # 텔레그램 메시지 구성
                    msg = (
                        f"🚨 [업비트 새 영상 등록 알림]\n\n"
                        f"📌 제목: {v['title']}\n"
                        f"🔗 링크: {v['link']}\n"
                        f"⏰ 게시 시간: {v['published']}"
                    )
                    
                    send_telegram_message(msg)
                    seen_video_ids.add(v_id)
                    save_seen_videos()
            
        except Exception as e:
            logging.error(f"감시 루프 중 에러: {e}")
            
        time.sleep(CHECK_INTERVAL)

# Render 배포 및 헬스체크를 위한 Flask 웹 앱
app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>Upbit YouTube Monitor Bot is Running!</h1>"

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "monitored_channel": CHANNEL_ID,
        "seen_count": len(seen_video_ids),
        "check_interval": CHECK_INTERVAL
    })

# 백그라운드 감시 스레드 시작
monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
monitor_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)