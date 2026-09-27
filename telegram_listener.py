#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Command Listener — รันบน GitHub Actions ทุก 5 นาที
เช็คข้อความใหม่ใน Telegram แล้วสั่งรัน sync.yml เมื่อเจอคำสั่ง

คำสั่งที่รองรับ (พิมพ์ได้เลย ไม่ต้องใช้ / นำหน้า เพราะ Hermes จะดัก /cmd ไปก่อน):
  sync | อัปเดท | อัพเดท | ซิงค์

Environment variables:
  TELEGRAM_BOT_TOKEN - token ของบอท
  TELEGRAM_CHAT_ID   - chat id ที่อนุญาตให้สั่ง (ถ้าไม่ตั้ง = ทุกแชท)
  GH_PAT             - GitHub PAT ที่มี scope repo + workflow
  GITHUB_REPOSITORY  - owner/repo (Actions ตั้งให้อัตโนมัติ)
"""
import os
import sys
import time
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
REPO = os.environ.get("GITHUB_REPOSITORY")

# คำสั่งที่ถือว่า "สั่งให้ซิงค์" — เป็นคำธรรมดา ไม่ขึ้นต้นด้วย /
SYNC_COMMANDS = {"sync", "/sync", "อัปเดท", "อัพเดท", "ซิงค์", "syncnow", "อัปเดต"}

# ข้อความเก่ากว่านี้วินาที = ไม่นับ (กันเผลอรันซ้ำจากคิวค้าง)
MAX_AGE_SEC = 300

missing = [n for n, v in {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "GH_PAT": GITHUB_TOKEN,
    "GITHUB_REPOSITORY": REPO,
}.items() if not v]
if missing:
    print("Missing env vars: " + ", ".join(missing))
    sys.exit(0)

api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def telegram(method, **params):
    return requests.get(f"{api}/{method}", params=params, timeout=15).json()


def reply(chat_id, text):
    requests.post(f"{api}/sendMessage",
                  json={"chat_id": chat_id, "text": text,
                        "parse_mode": "HTML"}, timeout=15)


now = time.time()

# --- 1. ดึงข้อความใหม่ ---
try:
    data = telegram("getUpdates")
except Exception as e:
    print(f"getUpdates failed: {e}")
    sys.exit(0)

if not data.get("ok"):
    print(f"Telegram API error: {data.get('description')}")
    sys.exit(0)

updates = data.get("result") or []
if not updates:
    print("No new messages.")
    sys.exit(0)

# --- 2. หาคำสั่งซิงค์ที่ยังไม่หมดอายุ ---
trigger_chat = None
latest_update_id = 0

for upd in updates:
    latest_update_id = max(latest_update_id, upd["update_id"])
    msg = upd.get("message") or upd.get("edited_message")
    if not msg:
        continue
    chat = msg.get("chat") or {}
    if TELEGRAM_CHAT_ID and str(chat.get("id")) != str(TELEGRAM_CHAT_ID):
        continue
    text = (msg.get("text") or "").strip().lower()
    if text in SYNC_COMMANDS and (now - msg.get("date", 0)) <= MAX_AGE_SEC:
        trigger_chat = chat.get("id")
        break

# --- 3. เคลียร์คิวทิ้งเสมอ (ไม่งั้นข้อความเก่าจะถูกอ่านซ้ำทุกรอบ) ---
if latest_update_id:
    telegram("getUpdates", offset=latest_update_id + 1)

if not trigger_chat:
    print("No sync command found.")
    sys.exit(0)

# --- 4. สั่งรัน sync.yml ---
print(f"Sync command from chat {trigger_chat} — dispatching sync.yml")
try:
    resp = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/sync.yml/dispatches",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": "master"},
        timeout=20,
    )
except Exception as e:
    print(f"Dispatch request failed: {e}")
    sys.exit(0)

if resp.status_code == 204:
    print("Dispatched OK (204)")
    reply(trigger_chat, "⏳ ได้รับคำสั่งซิงค์แล้ว\nกำลังดึงข้อมูลจาก COROS รอประมาณ 1-2 นาที")
else:
    print(f"Dispatch failed: {resp.status_code} {resp.text[:300]}")
    reply(trigger_chat, f"❌ สั่งซิงค์ไม่สำเร็จ ({resp.status_code})")
