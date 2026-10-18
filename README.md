# 🤖 Upgraded TikTok to Amharic Telegram Bot (የቲክቶክ ወደ አማርኛ ተርጓሚ ቦት)

An AI-powered Telegram bot that downloads TikTok videos, translates captions and speech into Amharic (አማርኛ), sends the audio track by itself, identifies background music and trending sounds, and supports multi-video batch hunting by username!

---

## 🌟 Super-Powers (ልዩ ችሎታዎች)

1. 📥 **Smart Video Link & Creator Detection:** Send any TikTok video link (`vm.tiktok.com/...`, `vt.tiktok.com/...`, or `tiktok.com/@...`) and choose whether to process just that single video OR fetch recent videos from that creator!
2. 👤 **Username Hunter:** Send a creator's username (e.g. `@adonaymada` or `@khaby.lame`).
3. ✍️ **Custom Video Count:** Write ANY number of videos you want (e.g. `4`, `7`, `10`, `15`) in chat, or pick with buttons!
4. 📝 **Dual Caption:** Displays the original caption AND translates the caption into Amharic.
5. 🎵 **Standalone Audio Track:** Sends the `.mp3` audio track separately so you can listen on Telegram's music player.
6. 🎶 **Background Music & Trend Audio Detective:** Detects the song title, artist, audio type, and vibe.
7. 🇪🇹 **Amharic Speech Transcriber:** Listens to the spoken words and writes them in Amharic Ge'ez script (ፊደል).
8. 💡 **Summary & Key Points:** Generates a 2-3 sentence summary and key takeaways in Amharic.
9. 📦 **Structured JSON Exports:** Download single JSON files or a master batch JSON file for the whole profile!

---

## 🚀 How to Run the Bot

### Option 1: Double-Click (Easiest)
Just double-click:
👉 `start_bot.bat`

### Option 2: Run via Terminal
```bash
.\venv\Scripts\python bot.py
```

---

## 📱 How to Use in Telegram

Bot: **[@TroveTiktok_bot](https://t.me/TroveTiktok_bot)**

- **Single video or Creator Batch by link:**
  - Send any video link: `https://www.tiktok.com/@adonaymada/video/...`
  - Choose `[ 🎬 1 ቪዲዮ (ይህን ብቻ) ]` for just that video, or tap a button / write any number (e.g. `10`) to get recent videos from that creator!
  - Or send link with count directly: `https://vm.tiktok.com/... 5`
- **Creator latest videos by username:**
  - Send `@adonaymada` -> pick with buttons OR write any number in chat (e.g. `4` or `12`)!
  - Or send directly: `@adonaymada 10`
