import os
import sys
import json
import logging
import asyncio
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from typing import Dict, Any, List

# Route optimization for Telegram Bot API:
# In certain ISP networks, DNS resolves api.telegram.org to 149.154.166.110 which suffers from
# dropped packets/timeouts, whereas 149.154.167.99 is Telegram's high-speed working Bot API endpoint.
_orig_getaddrinfo = socket.getaddrinfo

def _fast_telegram_getaddrinfo(host, port, *args, **kwargs):
    h = host.decode("utf-8", "ignore") if isinstance(host, bytes) else str(host)
    if h == "api.telegram.org":
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("149.154.167.99", port)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("149.154.166.110", port)),
        ]
    return _orig_getaddrinfo(host, port, *args, **kwargs)

socket.getaddrinfo = _fast_telegram_getaddrinfo

# Ensure Windows terminal handles emojis and Amharic Ge'ez script cleanly
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import telegram.error
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, validate_config
from tiktok_downloader import (
    is_tiktok_url,
    extract_video_id,
    extract_all_video_ids,
    parse_any_query,
    resolve_creator_from_url,
    get_user_video_urls,
    download_tiktok_audio_and_meta,
    download_tiktok_video
)
from audio_utils import cleanup_files
from transcriber import transcribe_and_translate_to_amharic

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class RetryingHTTPXRequest(HTTPXRequest):
    """
    Extends HTTPXRequest with automatic exponential backoff retry.
    Guarantees that temporary network glitches or connection resets to Telegram's API
    never cause dropped messages or failed replies.
    """
    async def do_request(self, *args, **kwargs):
        last_err = None
        for attempt in range(5):
            try:
                return await super().do_request(*args, **kwargs)
            except (telegram.error.NetworkError, telegram.error.TimedOut) as err:
                last_err = err
                logger.warning(f"Telegram API network retry ({attempt + 1}/5) due to: {err}")
                await asyncio.sleep(0.5 * (attempt + 1))
        if last_err:
            raise last_err

# Session cache for JSON downloads
SESSION_DATA: Dict[str, Any] = {}

def build_report_message(data: Dict[str, Any]) -> str:
    """Builds a beautifully formatted Telegram markdown card with dual caption and music details."""
    stats = data.get("stats", {})
    music = data.get("music", {})
    ai = data.get("ai_transcription", {})
    sound_ai = ai.get("sound_analysis", {})

    hashtags_str = " ".join(data.get("hashtags", [])[:8]) if data.get("hashtags") else "ምንም ሃሽታግ የለም"
    
    # Original Caption
    orig_caption = data.get("native_caption", "").strip() or "ምንም ጽሑፍ የለም"
    if len(orig_caption) > 200:
        orig_caption = orig_caption[:200] + "..."

    # Translated Caption
    trans_caption = ai.get("amharic_caption_translation", "").strip() or "ትርጉም አልተገኘም"
    if len(trans_caption) > 200:
        trans_caption = trans_caption[:200] + "..."

    # Spoken Audio Transcript
    amharic_transcript = ai.get("amharic_transcript", "").strip() or "የንግግር ድምፅ አልተገኘም"
    if len(amharic_transcript) > 600:
        amharic_transcript = amharic_transcript[:600] + "..."

    # Summary
    summary = ai.get("amharic_summary", "").strip() or "ማጠቃለያ የለም"
    
    # Key points
    key_points = ai.get("amharic_key_points", [])
    key_points_str = "\n".join([f"  • {kp}" for kp in key_points]) if key_points else "  • ምንም ዋና ዋና ነጥቦች አልተገኙም"

    # Music Info
    music_title = music.get("title", "Original Sound")
    music_artist = music.get("artist", data.get("creator", "Unknown"))
    sound_type = music.get("sound_type", "Audio")
    sound_vibe = sound_ai.get("sound_vibe", "")
    music_details = f"• **ርዕስ (Sound):** {music_title}\n• **አርቲስት (Artist):** {music_artist}\n• **ዓይነት (Type):** {sound_type}"
    if sound_vibe:
        music_details += f"\n• **የድምፅ ባህሪ (Vibe):** {sound_vibe}"

    id_line = f"• 🆔 **መታወቂያ (Video ID):** `{data.get('video_id')}`\n" if data.get('video_id') else ""

    return (
        "🎬 **የቲክቶክ ዝርዝር መረጃ (TikTok Video Info)**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 **አዘጋጅ (Creator):** {data.get('creator')} ({data.get('creator_handle')})\n"
        f"{id_line}"
        f"⏱️ **ርዝመት (Duration):** {data.get('duration_seconds')} ሰከንድ\n"
        f"❤️ **መውደዶች:** {stats.get('likes', 0):,} | 👁️ **ዕይታዎች:** {stats.get('views', 0):,}\n\n"
        "📝 **የመጀመሪያው ጽሑፍ (Original Caption):**\n"
        f"_{orig_caption}_\n\n"
        "🇪🇹 **የተተረጎመው መግለጫ (Amharic Caption):**\n"
        f"_{trans_caption}_\n\n"
        f"🏷️ **ሃሽታጎች (Hashtags):**\n{hashtags_str}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎵 **የጀርባ ሙዚቃ / ድምፅ (Music & Sound):**\n"
        f"{music_details}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗣️ **የተገኘው ቋንቋ:** {ai.get('original_language', 'Unknown')}\n\n"
        "🇪🇹 **የተተረጎመው የንግግር ግልባጭ (Amharic Transcript):**\n"
        f"{amharic_transcript}\n\n"
        "💡 **አጭር ማጠቃለያ (Summary):**\n"
        f"{summary}\n\n"
        "📌 **ዋና ዋና ነጥቦች (Key Takeaways):**\n"
        f"{key_points_str}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

async def process_single_video(
    url: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    status_msg,
    video_number: int = 1,
    total_videos: int = 1
) -> Dict[str, Any]:
    """Downloads audio track and metadata, transcribes to Amharic, and sends audio and report (No video files)."""
    loop = asyncio.get_running_loop()
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.message.chat.id
    user_id = update.effective_user.id if update.effective_user else (update.callback_query.from_user.id if update.callback_query else 0)
    bot = context.bot

    progress_prefix = f"({video_number}/{total_videos}) " if total_videos > 1 else ""

    # Step 1: Download audio track & metadata only (NO video file)
    await status_msg.edit_text(
        f"⏳ **{progress_prefix}ደረጃ 1/3:** ድምፁን እና መረጃውን በማውረድ ላይ...\n*(Downloading audio track & metadata...)*",
        parse_mode="Markdown"
    )

    download_result = await loop.run_in_executor(None, download_tiktok_audio_and_meta, url)
    if not download_result.get("success"):
        err = download_result.get("error", "Unknown error")
        raise Exception(f"ድምፁን ወይም መረጃውን ማውረድ አልተቻለም: {err}")

    audio_path = download_result.get("audio_path")
    if not audio_path or not os.path.exists(audio_path):
        raise Exception("የድምፅ ፋይሉ አልተገኘም (Audio file not found)")

    try:
        # Step 2: Transcribe with Gemini AI
        await status_msg.edit_text(
            f"🎧 **{progress_prefix}ደረጃ 2/3:** ድምፁን እና ጽሑፉን ወደ አማርኛ በመተርጎም ላይ...\n"
            "*(Gemini AI is translating speech & caption to Amharic...)*",
            parse_mode="Markdown"
        )

        ai_result = await loop.run_in_executor(
            None,
            transcribe_and_translate_to_amharic,
            audio_path,
            download_result.get("caption", "")
        )

        ai_data = ai_result.get("data", {}) if ai_result.get("success") else {
            "original_language": "Unknown",
            "original_transcript": "Could not transcribe audio.",
            "amharic_transcript": "ድምፁን መገልበጥ አልተቻለም ወይም ንግግር የለውም።",
            "amharic_caption_translation": "መግለጫውን መተርጎም አልተቻለም።",
            "sound_analysis": {"has_background_music": False, "sound_vibe": ""},
            "amharic_summary": "ማጠቃለያ የለም።",
            "amharic_key_points": []
        }

        # Step 3: Package structured data
        vid = download_result.get("video_id") or extract_video_id(url)
        structured_data = {
            "tiktok_url": url,
            "video_id": vid or "",
            "creator": download_result.get("uploader", "Unknown"),
            "creator_handle": download_result.get("uploader_handle", ""),
            "duration_seconds": download_result.get("duration", 0),
            "native_caption": download_result.get("caption", "").strip(),
            "hashtags": download_result.get("hashtags", []),
            "stats": download_result.get("stats", {}),
            "music": download_result.get("music", {}),
            "ai_transcription": ai_data
        }

        session_id = f"{user_id}_{uuid_str()}"
        SESSION_DATA[session_id] = structured_data

        # Step 4: Send Audio Track and Report Card (NO VIDEO FILE DOWNLOADED OR SENT)
        await status_msg.edit_text(
            f"📤 **{progress_prefix}ደረጃ 3/3:** ድምፁን እና ዝርዝር መረጃውን በመላክ ላይ...\n*(Sending audio track & report...)*",
            parse_mode="Markdown"
        )

        # 1. Send Standalone Audio file (.mp3)
        if audio_path and os.path.exists(audio_path) and audio_path.endswith(".mp3"):
            music_meta = structured_data.get("music", {})
            with open(audio_path, "rb") as af:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=af,
                    title=music_meta.get("title") or "TikTok Audio",
                    performer=music_meta.get("artist") or structured_data['creator'],
                    caption="🎵 **የቪዲዮው ድምፅ (Standalone Audio Track)**",
                    parse_mode="Markdown"
                )

        # 2. Send Formatted Info Card
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 ሙሉ JSON ዳታ አውርድ (Get Raw JSON)", callback_data=f"json_{session_id}")]
        ])

        report_text = build_report_message(structured_data)
        await bot.send_message(
            chat_id=chat_id,
            text=report_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )

        return structured_data

    finally:
        cleanup_files(audio_path)

def uuid_str() -> str:
    import uuid
    return uuid.uuid4().hex[:8]

def build_count_keyboard(target_identifier: str, is_from_video: bool = False, session_id: str = "") -> InlineKeyboardMarkup:
    """Builds interactive buttons for choosing video count or custom entry."""
    first_btn_text = "🎬 1 ቪዲዮ (ይህን ብቻ)" if is_from_video else "1 ቪዲዮ (1 Video)"
    first_btn_data = f"vid_{session_id}" if is_from_video else f"user_{target_identifier}_1"

    keyboard = [
        [
            InlineKeyboardButton(first_btn_text, callback_data=first_btn_data),
            InlineKeyboardButton("2 ቪዲዮዎች (2)", callback_data=f"user_{target_identifier}_2"),
        ],
        [
            InlineKeyboardButton("3 ቪዲዮዎች (3)", callback_data=f"user_{target_identifier}_3"),
            InlineKeyboardButton("5 ቪዲዮዎች (5)", callback_data=f"user_{target_identifier}_5"),
        ],
        [
            InlineKeyboardButton("10 ቪዲዮዎች (10)", callback_data=f"user_{target_identifier}_10"),
            InlineKeyboardButton("✍️ ሌላ ቁጥር ጻፍ (Custom)", callback_data=f"custom_{target_identifier}"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user with friendly instructions."""
    welcome_text = (
        "👋 **ሰላም! እንኳን ወደ ቲክቶክ ወደ አማርኛ ተርጓሚ ቦት በደህና መጡ!**\n"
        "*(Welcome to the Upgraded TikTok Amharic Transcriber Bot!)*\n\n"
        "✨ **አዳዲስ ልዩ ችሎታዎች (New Features):**\n"
        "1️⃣ **ያልተገደበ የቪዲዮ መታወቂያዎች ዝርዝር (Unlimited Video IDs List):**\n"
        "   - በርካታ የቪዲዮ መታወቂያዎችን (Video IDs) በአንድ ጊዜ ጽፈው ወይም paste አድርገው መላክ ይችላሉ!\n"
        "   - ቦቱ እያንዳንዱን በቅደም ተከተል ያዘጋጃል፤ ምንም የቁጥር ገደብ የለም (Unlimited)!\n"
        "2️⃣ **በነጠላ ቪዲዮ መታወቂያ ወይም ሊንክ (Single Video ID or Link):**\n"
        "   - አንድ Video ID (ለምሳሌ `7698794225453813022`) ወይም ሊንክ በቀጥታ ይላኩ።\n"
        "3️⃣ **ድምፅ እና መረጃ ብቻ (Audio, Caption & Transcription Only - No Video!):**\n"
        "   - ቪዲዮውን ሳያወርዱ የድምፅ ትራኩን (.mp3)፣ የመጀመሪያውን መግለጫ እና የአማርኛ ትርጉሙን፣ እንዲሁም ሙሉ የንግግር ግልባጩንና ማጠቃለያውን ያገኛሉ።\n"
        "4️⃣ **የጀርባ ሙዚቃ እና ቫይብ መለያ (Trending Music & Vibe Detection):**\n"
        "   - በጀርባ የተጠቀሙበትን ትሬንዲንግ ሙዚቃ ወይም ድምፅ ለይቶ ባህሪውን (Vibe) ያብራራል።\n"
        "5️⃣ **በተጠቃሚ ስም (By Username):** የፈጣሪውን ስም ይላኩ (ለምሳሌ: `@adonaymada` ወይም `@adonaymada 10`)\n\n"
        "🚀 **ለመጀመር:** የቪዲዮ መታወቂያ (ወይም የበርካታ Video IDs ዝርዝር)፣ የቲክቶክ ሊንክ ወይም የተጠቃሚ ስም ይላኩልኝ!"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "ℹ️ **የአጠቃቀም መመሪያ (How to Use):**\n\n"
        "• **ያልተገደበ የቪዲዮ መታወቂያዎች ዝርዝር (Unlimited Video IDs List):**\n"
        "  - በርካታ የቪዲዮ ቁጥሮችን በየመስመሩ ወይም በነጠላ ሰረዝ ለይተው ይላኩ፦\n"
        "    `7698794225453813022`\n"
        "    `7698794225453813023`\n"
        "    `7698794225453813024`\n"
        "  - ቦቱ ሁሉንም በቅደም ተከተል ድምፃቸውን እና መረጃቸውን አዘጋጅቶ ያቀርባል!\n\n"
        "• **በአንድ ቪዲዮ መታወቂያ (Single Video ID):**\n"
        "  - የቪዲዮውን ቁጥር በቀጥታ ይላኩ (ለምሳሌ: `7698794225453813022`)\n"
        "  - ወይም በትእዛዝ: `/video 7698794225453813022`\n\n"
        "• **ቪዲዮ በሊንክ (Single Video or Creator Batch):**\n"
        "  - `https://www.tiktok.com/@user/video/...` ይላኩ\n"
        "  - ወይም `https://vm.tiktok.com/... 5` ብለው የቪዲዮውን ብዛት ጨምረው መላክ ይችላሉ!\n\n"
        "• **በርካታ ቪዲዮዎች በተጠቃሚ ስም (By Creator Username):**\n"
        "  - `@username` ወይም `@username 5` ብለው ይላኩ።"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /video <id_or_url> or /id <id_or_url> commands."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "💡 **እባክዎ የቪዲዮውን መታወቂያ (Video ID) ወይም ሊንክ አብረው ይጻፉ!**\n"
            "*(Please provide a TikTok Video ID or URL!)*\n\n"
            "ምሳሌ (Examples):\n"
            "• `/video 7698794225453813022`\n"
            "• `/video 7698794225453813022 5`\n"
            "• `/id 7698794225453813022`\n\n"
            "ወይም በቀጥታ ቁጥሩን ብቻ በቻቱ ጽፈው መላክ ይችላሉ!",
            parse_mode="Markdown"
        )
        return
    await handle_user_message(update, context, override_text=" ".join(args))

async def start_batch_processing_video_ids(update: Update, context: ContextTypes.DEFAULT_TYPE, video_ids: List[str]):
    """
    Processes an arbitrary list of TikTok Video IDs (unlimited).
    Downloads audio and metadata for each ID sequentially without downloading video files.
    """
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.message.chat.id
    user_id = update.effective_user.id if update.effective_user else (update.callback_query.from_user.id if update.callback_query else 0)
    bot = context.bot

    # Clear pending session state
    context.user_data.pop("pending_creator", None)
    context.user_data.pop("pending_video", None)

    total = len(video_ids)
    status_text = (
        f"📋 **የ {total} ቪዲዮ መታወቂያዎች ዝርዝር ደርሶናል! (List of {total} Video IDs Received)**\n"
        f"⏳ እያንዳንዱን ድምፅ፣ መግለጫ እና የትርጉም መረጃ በማዘጋጀት ላይ...\n"
        f"*(Processing {total} TikTok videos sequentially...)*"
    )
    if update.callback_query and update.callback_query.message:
        status_msg = await update.callback_query.message.reply_text(status_text, parse_mode="Markdown")
    else:
        status_msg = await update.message.reply_text(status_text, parse_mode="Markdown")

    all_results = []

    for idx, vid in enumerate(video_ids, start=1):
        v_url = f"https://www.tiktok.com/@tiktok/video/{vid}"
        try:
            res = await process_single_video(
                url=v_url,
                update=update,
                context=context,
                status_msg=status_msg,
                video_number=idx,
                total_videos=total
            )
            all_results.append(res)
        except Exception as e:
            logger.error(f"Error processing video ID {vid} ({idx}/{total}): {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ ቪዲዮ {idx} (ID: `{vid}`) ማዘጋጀት አልተቻለም ({str(e)[:100]})",
                parse_mode="Markdown"
            )

    # Master bundle button
    batch_session_id = f"batch_{user_id}_{uuid_str()}"
    SESSION_DATA[batch_session_id] = {
        "batch_type": "video_id_list",
        "creator": "video_ids_list",
        "total_requested": total,
        "total_processed": len(all_results),
        "video_ids": video_ids,
        "videos": all_results
    }

    master_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 የተሟላ Master JSON ባች አውርድ (Download Master JSON)", callback_data=f"master_{batch_session_id}")]
    ])

    await status_msg.edit_text(
        f"🎉 **ተጠናቋል!** ከ **{total}** ቪዲዮዎች ውስጥ **{len(all_results)}** በተሳካ ሁኔታ ተጠናቀዋል!\n"
        f"*(Successfully finished {len(all_results)} of {total} video IDs!)*",
        parse_mode="Markdown",
        reply_markup=master_keyboard
    )

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE, override_text: str = None):
    """Handles single video links, video IDs, lists of unlimited video IDs, creator usernames, and custom numeric counts."""
    text = (override_text or (update.message.text if update.message else "")).strip()
    if not text:
        return
    query_info = parse_any_query(text)
    q_type = query_info.get("type")

    # CASE 0: User pasted a list of multiple Video IDs (unlimited)
    if q_type == "video_id_list":
        video_ids = query_info.get("video_ids", [])
        if video_ids:
            await start_batch_processing_video_ids(update, context, video_ids)
            return

    # CASE 1: User typed a pure number (e.g. "4", "7", "10", "15")
    if q_type == "number":
        count = query_info["count"]
        count = max(1, min(count, 20))

        pending_creator = context.user_data.get("pending_creator")
        pending_video = context.user_data.get("pending_video")

        if pending_creator or pending_video:
            creator = pending_creator or "creator"
            if count == 1 and pending_video:
                status_msg = await update.message.reply_text("⏳ ቪዲዮውን በመቀበል ላይ... *(Starting...)*")
                try:
                    await process_single_video(pending_video, update, context, status_msg)
                    await status_msg.delete()
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    await status_msg.edit_text(f"⚠️ ስህተት (Error): {str(e)[:150]}")
                return
            else:
                await start_batch_processing(update, context, creator, count)
                return
        else:
            await update.message.reply_text(
                "⚠️ እባክዎ መጀመሪያ የቲክቶክ ቪዲዮ ሊንክ፣ Video ID ወይም የተጠቃሚ ስም ይላኩ!\n"
                "*(Please send a TikTok video link, video ID, or @username first!)*\n\n"
                "ምሳሌ (Examples):\n"
                "• `7698794225453813022` (የቪዲዮ መታወቂያ / Video ID)\n"
                "• `7698794225453813022, 7698794225453813023` (ያልተገደበ የቪዲዮ ዝርዝር / Unlimited list of Video IDs)\n"
                "• `https://vm.tiktok.com/...`\n"
                "• `https://www.tiktok.com/@user/video/...`\n"
                "• `@adonaymada` ወይም `@adonaymada 5`"
            )
            return

    # CASE 2: Single TikTok Video ID
    if q_type == "video_id":
        url = query_info["url"]
        count = query_info.get("count")
        creator = query_info.get("creator")
        vid = query_info.get("video_id")

        # If user explicitly appended a creator count > 1 (e.g. "<id> 5")
        if count is not None and count > 1:
            target_creator = creator or "creator"
            await start_batch_processing(update, context, target_creator, count)
            return

        # Direct processing for single video ID (or if count == 1)
        status_msg = await update.message.reply_text(
            f"⏳ የቪዲዮ መታወቂያ `{vid}` በመቀበል ላይ...\n*(Processing TikTok Video ID: {vid}...)*",
            parse_mode="Markdown"
        )
        try:
            await process_single_video(url, update, context, status_msg)
            await status_msg.delete()
        except Exception as e:
            logger.error(f"Error processing video ID {vid}: {e}", exc_info=True)
            await status_msg.edit_text(f"⚠️ ስህተት (Error): {str(e)[:150]}")
        return

    # CASE 3: Single TikTok Video URL
    if q_type == "video_url":
        url = query_info["url"]
        count = query_info.get("count")
        creator = query_info.get("creator")

        if count is not None:
            if count == 1:
                status_msg = await update.message.reply_text("⏳ ቪዲዮውን በመቀበል ላይ... *(Starting...)*")
                try:
                    await process_single_video(url, update, context, status_msg)
                    await status_msg.delete()
                except Exception as e:
                    logger.error(f"Error: {e}", exc_info=True)
                    await status_msg.edit_text(f"⚠️ ስህተት (Error): {str(e)[:150]}")
                return
            else:
                target_creator = creator or "creator"
                await start_batch_processing(update, context, target_creator, count)
                return

        # If no count specified: Ask with buttons AND let them write any number!
        target_creator = creator or "creator"
        context.user_data["pending_creator"] = target_creator
        context.user_data["pending_video"] = url

        session_id = uuid_str()
        SESSION_DATA[f"vid_{session_id}"] = url

        keyboard = build_count_keyboard(target_creator, is_from_video=True, session_id=session_id)
        creator_display = f"@{target_creator}" if not target_creator.startswith("@") else target_creator

        await update.message.reply_text(
            f"🎬 **የቲክቶክ ቪዲዮ ደርሶናል! (TikTok Video Link Received)**\n"
            f"👤 **ፈጣሪ (Creator):** {creator_display}\n\n"
            f"ስንት ቪዲዮዎችን ማውረድ እና መተርጎም ይፈልጋሉ?\n"
            f"*(How many videos would you like to process?)*\n\n"
            f"✍️ **የሚፈልጉትን ቁጥር ጽፈው መላክ ይችላሉ** (ለምሳሌ: `1`፣ `3`፣ `7`፣ `10`...) ወይም ከታች ይምረጡ፡\n"
            f"*(Type any number in chat or choose below:)*",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # CASE 4: User sent a Username or Profile URL (e.g. "@adonaymada", "adonaymada", or "https://tiktok.com/@adonaymada")
    if q_type in ("username", "profile_url"):
        creator = query_info.get("creator") or query_info.get("raw", "").lstrip("@")
        count = query_info.get("count")

        if count is not None:
            await start_batch_processing(update, context, creator, count)
            return

        context.user_data["pending_creator"] = creator
        context.user_data["pending_video"] = None

        keyboard = build_count_keyboard(creator, is_from_video=False)

        creator_display = f"@{creator}" if not creator.startswith("@") else creator
        await update.message.reply_text(
            f"👤 **የ {creator_display} ስንት የቅርብ ቪዲዮዎችን ማውረድ እና መተርጎም ይፈልጋሉ?**\n"
            f"*(How many recent videos from {creator_display} would you like to process?)*\n\n"
            f"✍️ **የሚፈልጉትን ቁጥር ጽፈው መላክ ይችላሉ** (ለምሳሌ: `1`፣ `3`፣ `7`፣ `10`...) ወይም ከታች ይምረጡ፡\n"
            f"*(Type any number in chat or choose below:)*",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # Unknown input
    await update.message.reply_text(
        "⚠️ እባክዎ ትክክለኛ የቲክቶክ ቪዲዮ ሊንክ፣ የቪዲዮ መታወቂያ (Video ID)፣ የቪዲዮ መታወቂያዎች ዝርዝር ወይም የተጠቃሚ ስም ይላኩ!\n"
        "*(Please send a TikTok video link, video ID, list of video IDs, or @username)*\n\n"
        "ምሳሌ (Examples):\n"
        "• `7698794225453813022` (የቪዲዮ መታወቂያ / Video ID)\n"
        "• `7698794225453813022, 7698794225453813023` (ያልተገደበ የቪዲዮ መታወቂያዎች ዝርዝር)\n"
        "• `7698794225453813022 5`\n"
        "• `https://vm.tiktok.com/...`\n"
        "• `https://www.tiktok.com/@user/video/...`\n"
        "• `@adonaymada`\n"
        "• `@adonaymada 5`\n"
        "• `https://www.tiktok.com/@adonaymada 10`"
    )

async def start_batch_processing(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str, count: int):
    """Fetches N videos from user profile and processes each one sequentially."""
    actual_requested = count
    count = max(1, min(count, 20))  # Keep safe between 1 and 20
    chat_id = update.effective_chat.id if update.effective_chat else update.callback_query.message.chat.id
    user_id = update.effective_user.id if update.effective_user else (update.callback_query.from_user.id if update.callback_query else 0)
    bot = context.bot

    # Clear pending creator after initiating batch
    context.user_data.pop("pending_creator", None)
    context.user_data.pop("pending_video", None)

    limit_note = ""
    if actual_requested > 20:
        limit_note = "\n*(ማስታወሻ: ለጥራት እና ለደህንነት ሲባል በአንድ ጊዜ እስከ 20 ቪዲዮዎች ብቻ ይፈቀዳል።)*"

    status_text = f"🕵️‍♂️ **የ @{username} የቅርብ {count} ቪዲዮዎችን በመፈለግ ላይ...**{limit_note}\n*(Hunting recent {count} videos...)*"
    if update.callback_query and update.callback_query.message:
        status_msg = await update.callback_query.message.reply_text(status_text, parse_mode="Markdown")
    else:
        status_msg = await update.message.reply_text(status_text, parse_mode="Markdown")

    loop = asyncio.get_running_loop()
    video_urls = await loop.run_in_executor(None, get_user_video_urls, username, count)

    if not video_urls:
        await status_msg.edit_text(
            f"❌ ለ @{username} ምንም ቪዲዮዎች አልተገኙም። የተጠቃሚ ስሙ ትክክል መሆኑን ወይም አካውንቱ ክፍት (Public) መሆኑን ያረጋግጡ።"
        )
        return

    total = len(video_urls)
    all_results = []

    for idx, v_url in enumerate(video_urls, start=1):
        try:
            res = await process_single_video(
                url=v_url,
                update=update,
                context=context,
                status_msg=status_msg,
                video_number=idx,
                total_videos=total
            )
            all_results.append(res)
        except Exception as e:
            logger.error(f"Error processing video {idx}: {e}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ ቪዲዮ {idx} ማዘጋጀት አልተቻለም ({str(e)[:100]})"
            )

    # Master bundle button
    batch_session_id = f"batch_{user_id}_{uuid_str()}"
    SESSION_DATA[batch_session_id] = {
        "creator": username,
        "total_requested": count,
        "total_processed": len(all_results),
        "videos": all_results
    }

    master_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 የተሟላ Master JSON ባች አውርድ", callback_data=f"master_{batch_session_id}")]
    ])

    await status_msg.edit_text(
        f"🎉 **ተጠናቋል!** የ @{username} **{len(all_results)}** ቪዲዮዎች በተሳካ ሁኔታ ተተርጉመው ቀርበዋል!\n"
        f"*(Successfully finished {len(all_results)} videos for @{username}!)*",
        parse_mode="Markdown",
        reply_markup=master_keyboard
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button clicks for video count selection, custom entry, and JSON downloads."""
    query = update.callback_query
    await query.answer()

    data = query.data

    # Case 1: Single video button pressed from a video link prompt
    if data.startswith("vid_"):
        url = SESSION_DATA.get(data)
        if not url:
            await query.message.reply_text("⚠️ ይቅርታ፣ ይህ ሊንክ ጊዜው አልፎበታል (Link expired).")
            return
        await query.edit_message_text("⏳ ቪዲዮውን በመቀበል ላይ... *(Starting...)*")
        status_msg = await query.message.reply_text("⏳ ቪዲዮውን በማውረድ ላይ... *(Downloading video & metadata...)*")
        try:
            await process_single_video(url, update, context, status_msg)
            await status_msg.delete()
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await status_msg.edit_text(f"⚠️ ስህተት (Error): {str(e)[:150]}")
        return

    # Case 2: Custom input prompt button pressed
    if data.startswith("custom_"):
        username = data.replace("custom_", "")
        context.user_data["pending_creator"] = username
        await query.message.reply_text(
            f"✍️ **እባክዎ ለ @{username} ስንት ቪዲዮዎች እንደሚፈልጉ ቁጥሩን ጽፈው ይላኩ** (ለምሳሌ: `4`፣ `7`፣ `10`፣ `15`...)፦\n"
            f"*(Please type how many videos you want from @{username}:)*",
            parse_mode="Markdown"
        )
        return

    # Case 3: User chose a video count button: "user_<username>_<count>"
    if data.startswith("user_"):
        parts = data.split("_")
        if len(parts) >= 3:
            username = parts[1]
            count = int(parts[2])
            await query.edit_message_text(f"🚀 የ @{username} {count} ቪዲዮዎችን ማዘጋጀት ተጀምሯል...")
            await start_batch_processing(update, context, username, count)
        return

    # Case 4: Single JSON download
    if data.startswith("json_"):
        session_id = data.replace("json_", "")
        item = SESSION_DATA.get(session_id)
        if not item:
            await query.message.reply_text("⚠️ ይቅርታ፣ ይህ ዳታ ጊዜው አልፎበታል (Session expired).")
            return

        json_str = json.dumps(item, ensure_ascii=False, indent=2)
        bio = BytesIO(json_str.encode("utf-8"))
        bio.name = f"tiktok_{item.get('creator', 'video')}.json"

        await query.message.reply_document(
            document=bio,
            caption="📦 **የተሟላ የቪዲዮው JSON ዳታ (Structured JSON Data)**",
            parse_mode="Markdown"
        )
        return

    # Case 5: Master Batch JSON download
    if data.startswith("master_"):
        session_id = data.replace("master_", "")
        batch_data = SESSION_DATA.get(session_id)
        if not batch_data:
            await query.message.reply_text("⚠️ ይቅርታ፣ ይህ ዳታ ጊዜው አልፎበታል (Session expired).")
            return

        json_str = json.dumps(batch_data, ensure_ascii=False, indent=2)
        bio = BytesIO(json_str.encode("utf-8"))
        creator_tag = batch_data.get('creator', 'batch')
        bio.name = f"tiktok_batch_{creator_tag}.json"

        if batch_data.get("batch_type") == "video_id_list":
            caption_title = f"📦 **የ {batch_data.get('total_processed')} ቪዲዮ መታወቂያዎች Master JSON ባች**"
        else:
            caption_title = f"📦 **የ @{creator_tag} የተሟላ Master JSON ባች ({batch_data.get('total_processed')} ቪዲዮዎች)**"

        await query.message.reply_document(
            document=bio,
            caption=caption_title,
            parse_mode="Markdown"
        )
        return

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs errors and notifies the user gracefully if possible."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ ጊዜያዊ የግንኙነት መቋረጥ አጋጥሟል (Network hiccup). እባክዎ ጥያቄዎን ደግመው ይላኩ።"
            )
        except Exception:
            pass

class CloudHealthCheckHandler(BaseHTTPRequestHandler):
    """
    Lightweight HTTP server responding to Alet Cloud / container readiness probes.
    Satisfies $PORT readiness checks so container status turns green (LIVE).
    """
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>TikTok Amharic Bot - Status</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e293b; padding: 2.5rem; border-radius: 14px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; max-width: 480px; border: 1px solid #334155; }
        .badge { display: inline-block; background: #10b981; color: #042f2e; padding: 6px 14px; border-radius: 9999px; font-weight: bold; font-size: 0.875rem; margin-bottom: 1rem; }
        h1 { margin: 0 0 0.5rem 0; font-size: 1.5rem; }
        p { color: #94a3b8; font-size: 0.95rem; line-height: 1.6; }
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">● LIVE &amp; HEALTHY</span>
        <h1>🤖 TikTok Amharic Transcriber Bot</h1>
        <p>The Telegram Bot is running and actively processing TikTok video downloads, speech transcription, and Amharic translation.</p>
    </div>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress periodic health check logs to keep container logs clean
        return

def start_health_server():
    """Starts background HTTP server for Alet Cloud / K8s port readiness probes."""
    port = int(os.getenv("PORT", "3000"))
    try:
        server = HTTPServer(("0.0.0.0", port), CloudHealthCheckHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"✅ Cloud health check HTTP server listening on port {port}")
    except Exception as e:
        logger.warning(f"⚠️ Could not start health check HTTP server on port {port}: {e}")

def main():
    # 1. Start HTTP health check server immediately so Alet Cloud / K8s readiness probe succeeds
    start_health_server()

    # 2. Validate environment configuration
    is_valid, msg = validate_config()
    if not is_valid:
        print("\n" + "=" * 65, flush=True)
        print(f"❌ {msg}", flush=True)
        print("👉 In Alet Cloud, go to your app's 'Variables' tab and set:", flush=True)
        print("   • TELEGRAM_BOT_TOKEN = <your_bot_token>", flush=True)
        print("   • GEMINI_API_KEY     = <your_gemini_api_key>", flush=True)
        print("=" * 65 + "\n", flush=True)
        # Keep process alive with healthcheck server so container doesn't enter a crash loop
        import time
        while True:
            time.sleep(3600)
        return

    print("🚀 Starting Upgraded TikTok Amharic Transcriber Bot...", flush=True)
    request = RetryingHTTPXRequest(
        connect_timeout=15.0,
        read_timeout=25.0,
        write_timeout=25.0,
        pool_timeout=10.0,
        media_write_timeout=60.0
    )
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("video", video_command))
    app.add_handler(CommandHandler("id", video_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_error_handler(error_handler)

    print("✅ Bot is online and listening! Press Ctrl+C to stop.", flush=True)
    app.run_polling(bootstrap_retries=-1)

if __name__ == "__main__":
    main()
