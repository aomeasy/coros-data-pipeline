#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import requests
import datetime

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY")

if not all([TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, REPO]):
    print("Missing required environment variables.")
    sys.exit(0)

# เช็ค Update ล่าสุดจาก Telegram (ดูเฉพาะข้อความที่ไม่เก่าเกิน 15 นาที)
url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
try:
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
except Exception as e:
    print(f"Failed to fetch Telegram updates: {e}")
    sys.exit(0)

if not data.get("ok") or not data.get("result"):
    print("No updates found.")
    sys.exit(0)

# ค้นหาคำสั่ง /sync ล่าสุด
found_sync = False
latest_update_id = 0
now_ts = datetime.datetime.now().timestamp()

for item in data["result"]:
    latest_update_id = max(latest_update_id, item["update_id"])
    msg = item.get("message")
    if not msg:
        continue
    
    # กรองเฉพาะแชทที่ถูกต้อง (ถ้ามีการตั้ง CHAT_ID ไว้)
    if TELEGRAM_CHAT_ID and str(msg["chat"]["id"]) != TELEGRAM_CHAT_ID:
        continue
        
    text = msg.get("text", "").strip()
    date_ts = msg.get("date", 0)
    
    # ถ้าพิมพ์ /sync และเป็นข้อความใน 10 นาทีที่ผ่านมา
    if text == "/sync" and (now_ts - date_ts) < 600:
        found_sync = True

if found_sync:
    print("Found /sync command! Triggering sync.yml workflow...")
    # ยิง Trigger GitHub Action (sync.yml)
    gh_url = f"https://api.github.com/repos/{REPO}/actions/workflows/sync.yml/dispatches"
    gh_headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    gh_payload = {"ref": "master"}
    
    try:
        gh_resp = requests.post(gh_url, headers=gh_headers, json=gh_payload)
        if gh_resp.status_code in [204, 201, 200]:
            print("Triggered successfully.")
            # ตอบกลับ Telegram ว่ากำลังทำ
            send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(send_url, json={
                "chat_id": TELEGRAM_CHAT_ID or msg["chat"]["id"],
                "text": "⏳ ได้รับคำสั่ง /sync... กำลังดึงข้อมูลจาก COROS กรุณารอ 1-2 นาที"
            })
        else:
            print(f"Failed to trigger GitHub Actions: {gh_resp.status_code} {gh_resp.text}")
    except Exception as e:
        print(f"Error triggering workflow: {e}")

# เคลียร์ Update คิวทิ้ง เพื่อไม่ให้อ่านข้อความเดิมซ้ำรอบหน้า
if latest_update_id > 0:
    requests.get(f"{url}?offset={latest_update_id + 1}")
