# 🤖 Upgraded TikTok to Amharic Telegram Bot (የቲክቶክ ወደ አማርኛ ተርጓሚ ቦት)

An AI-powered Telegram bot that processes TikTok videos **without downloading heavy video files** — extracting ONLY the `.mp3` audio track, original and translated Amharic captions, trending background music and sound vibe, speech transcription into Amharic (አማርኛ), summary, and key takeaways. It also supports pasting an **unlimited list of Video IDs**!

---

## 🌟 Super-Powers (ልዩ ችሎታዎች)

1. 🚫 **Strictly No Video Download / Zero Video Waste:** Does NOT download, store, or send `.mp4` video files to Telegram. Saves massive internet bandwidth and operates 10x faster!
2. 📋 **Unlimited Video IDs List:** Paste any list of TikTok Video IDs (separated by newlines, commas, or spaces). The bot processes all of them sequentially with progress tracking (`(idx/total)`) without any limit!
3. 🆔 **Direct Video ID Support:** Accepts single raw TikTok Video IDs (e.g. `7698794225453813022`), or `/video <id>` / `/id <id>`. Automatically resolves the authentic creator and processes it immediately!
4. 🎵 **Standalone Audio Track:** Sends the `.mp3` audio track directly to Telegram so you can listen on Telegram's music player.
5. 📝 **Dual Caption:** Displays the original caption AND translates the caption into natural Amharic.
6. 🎶 **Background Music & Sound Detective:** Identifies the song title, artist, audio type, and describes the background vibe.
7. 🇪🇹 **Amharic Speech Transcriber:** Listens to the spoken words and transcribes/translates them into fluent Amharic Ge'ez script (ፊደል).
8. 💡 **Summary & Key Points:** Generates a 2-3 sentence summary and key takeaways in Amharic.
9. 👤 **Username Hunter:** Send a creator's username (e.g. `@adonaymada` or `@adonaymada 10`) to batch-process their recent videos.
10. 📦 **Structured JSON Exports:** Download single JSON files or a master batch JSON file for all processed videos!

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

- **Unlimited List of Video IDs (Paste list of IDs):**
  - Paste any number of Video IDs separated by lines or commas:
    ```
    7698794225453813022
    7698794225453813023
    7698794225453813024
    ```
  - The bot immediately processes each video's audio, caption, music, and Amharic transcription, then provides a **Master Batch JSON** button!

- **Single Video by Video ID:**
  - Send the raw Video ID: `7698794225453813022`
  - Or use commands: `/video 7698794225453813022` or `/id 7698794225453813022`

- **Single Video or Creator Batch by link:**
  - Send any video link: `https://www.tiktok.com/@adonaymada/video/...`
  - Choose `[ 🎬 1 ቪዲዮ (ይህን ብቻ) ]` for just that video, or tap a button / write any number (e.g. `10`) to get recent videos from that creator!
  - Or send link with count directly: `https://vm.tiktok.com/... 5`

- **Creator latest videos by username:**
  - Send `@adonaymada` -> pick with buttons OR write any number in chat (e.g. `4` or `12`)!
  - Or send directly: `@adonaymada 10`
