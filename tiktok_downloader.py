import os
import re
import uuid
import subprocess
from typing import Dict, Any, List, Optional, Tuple
import requests
import yt_dlp
import imageio_ffmpeg

from config import DOWNLOADS_DIR

# Robust regex matching all TikTok video, photo, short URL, and profile variations
TIKTOK_URL_REGEX = re.compile(
    r'(https?://)?(www\.|vm\.|vt\.|m\.)?tiktok\.com/[^\s]+',
    re.IGNORECASE
)

# TikTok Video IDs are 15-22 digit numeric snowflake IDs (typically 18-19 digits)
TIKTOK_VIDEO_ID_REGEX = re.compile(r'\b(\d{15,22})\b')

# Detects username with optional count (e.g. "@adonaymada" or "@adonaymada 5" or "adonaymada 10")
USERNAME_REGEX = re.compile(
    r'^@?([a-zA-Z0-9_\.]{2,30})(?:\s+(\d+))?$',
    re.IGNORECASE
)

MOBILE_USER_AGENT = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
)

DESKTOP_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def is_tiktok_url(url: str) -> bool:
    """Checks if a string contains or looks like a valid TikTok link."""
    return bool(TIKTOK_URL_REGEX.search(url))

def extract_video_id(text: str) -> Optional[str]:
    """
    Extracts a single TikTok video ID (15 to 22 digits) from a raw ID string,
    URL path (/video/12345..., /photo/12345...), or text.
    """
    if not text:
        return None
    url_m = re.search(r'(?:/video/|/v/|/photo/|item_id=|modal_id=)(\d{15,22})', text, re.IGNORECASE)
    if url_m:
        return url_m.group(1)
    m = TIKTOK_VIDEO_ID_REGEX.search(text)
    if m:
        return m.group(1)
    return None

def extract_all_video_ids(text: str) -> List[str]:
    """
    Extracts all unique TikTok video IDs (15 to 22 digits) from arbitrary text,
    a multi-line list, comma/space-separated list, or URLs.
    Preserves input order. Supports unlimited video IDs.
    """
    if not text:
        return []
    matches = TIKTOK_VIDEO_ID_REGEX.findall(text)
    seen = set()
    unique_ids = []
    for vid in matches:
        if vid not in seen:
            seen.add(vid)
            unique_ids.append(vid)
    return unique_ids

def is_tiktok_video_id(text: str) -> bool:
    """Checks if a string represents or contains a valid TikTok video ID."""
    return extract_video_id(text) is not None

def extract_hashtags(text: str) -> List[str]:
    """Finds all hashtags in text, including English and Amharic Ge'ez script hashtags."""
    if not text:
        return []
    matches = re.findall(r'#([\w\u1200-\u137F]+)', text)
    seen = set()
    result = []
    for tag in matches:
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen.add(tag_lower)
            result.append("#" + tag)
    return result

def resolve_creator_from_url(url: str) -> Optional[str]:
    """
    Extracts the creator username from a TikTok link, video ID, or profile.
    Automatically handles raw video IDs, short links, and placeholder URLs.
    """
    if not url:
        return None

    clean = url.strip()
    vid = extract_video_id(clean)

    # 1. Direct match in URL (e.g. tiktok.com/@adonaymada/...)
    m = re.search(r'tiktok\.com/@([a-zA-Z0-9_\.]+)', clean, re.IGNORECASE)
    if m:
        extracted = m.group(1).rstrip('/')
        # If genuine creator and not a generic placeholder
        if extracted.lower() not in ('tiktok', 'placeholder', '_', 'video', 'a', 'i', 'user') or not vid:
            return extracted

    # 2. If short URL (vm.tiktok.com, vt.tiktok.com, /t/), follow HTTP redirect
    if any(domain in clean.lower() for domain in ['vm.tiktok.com', 'vt.tiktok.com', '/t/']):
        try:
            headers = {'User-Agent': MOBILE_USER_AGENT}
            resp = requests.head(clean, headers=headers, allow_redirects=True, timeout=6)
            final_url = resp.url
            m = re.search(r'tiktok\.com/@([a-zA-Z0-9_\.]+)', final_url, re.IGNORECASE)
            if m:
                return m.group(1).rstrip('/')
        except Exception:
            pass

    # 3. Query TikWM metadata to get authentic creator handle
    query_target = vid if vid else clean
    try:
        headers = {'User-Agent': DESKTOP_USER_AGENT}
        r = requests.post("https://www.tikwm.com/api/", data={"url": query_target}, headers=headers, timeout=6)
        d = r.json()
        if d.get("code") == 0:
            uid = d.get("data", {}).get("author", {}).get("unique_id")
            if uid:
                return uid
    except Exception:
        pass

    # 4. Fallback: yt-dlp flat extraction if video ID is known
    if vid:
        try:
            target_url = f"https://www.tiktok.com/@tiktok/video/{vid}"
            ydl_opts = {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
                'http_headers': {'User-Agent': MOBILE_USER_AGENT}
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
                uploader = info.get("uploader") or info.get("uploader_id")
                if uploader and not uploader.isdigit():
                    return uploader
        except Exception:
            pass

    return None

def parse_any_query(text: str) -> Dict[str, Any]:
    """
    Parses user input into structured intent:
    - video_id_list: list of multiple video IDs (unlimited)
    - pure small number: "4", "10" (custom video count)
    - single video ID: "7698794225453813022" or "7698794225453813022 5" or "id: 7698794225453813022"
    - video link with optional count: "https://... 5"
    - profile link with optional count: "https://tiktok.com/@user 3"
    - username with optional count: "@adonaymada" or "@adonaymada 10"
    """
    cleaned = text.strip()

    # 1. Check if user typed or pasted a list of multiple video IDs (unlimited)
    all_vids = extract_all_video_ids(cleaned)
    if len(all_vids) >= 2:
        return {
            "type": "video_id_list",
            "video_ids": all_vids,
            "total": len(all_vids),
            "raw": cleaned
        }

    # 2. Pure number count (e.g. "4", "10", "15") - strictly less than 15 digits
    if cleaned.isdigit() and len(cleaned) < 15:
        return {
            "type": "number",
            "count": int(cleaned),
            "raw": cleaned
        }

    # 3. Extract potential trailing count (e.g. "... 5")
    parts = cleaned.rsplit(maxsplit=1)
    target = cleaned
    count = None
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) < 15:
        target = parts[0].strip()
        count = int(parts[1])

    # 4. Check if TikTok URL
    if is_tiktok_url(target) or "tiktok.com" in target.lower():
        words = target.split()
        target_url = next((w for w in words if "tiktok.com" in w), target)
        # Normalize /video/<id> if missing @user prefix so yt-dlp won't reject with Unsupported URL
        if "/video/" in target_url and "@" not in target_url:
            target_url = re.sub(r'tiktok\.com/video/(\d+)', r'tiktok.com/@tiktok/video/\1', target_url)
        creator = resolve_creator_from_url(target_url)
        vid = extract_video_id(target_url)
        is_single_video = any(k in target_url.lower() for k in ["/video/", "/photo/", "vm.tiktok.com", "vt.tiktok.com", "/t/"])
        return {
            "type": "video_url" if is_single_video else "profile_url",
            "url": target_url,
            "creator": creator,
            "video_id": vid,
            "count": count,
            "raw": cleaned
        }

    # 5. Check if Single Video ID (standalone 15-22 digits, or "id: 12345...", "video 12345...")
    vid = extract_video_id(target)
    if vid:
        creator = resolve_creator_from_url(vid)
        canonical_creator = creator if creator else "tiktok"
        canonical_url = f"https://www.tiktok.com/@{canonical_creator}/video/{vid}"
        return {
            "type": "video_id",
            "video_id": vid,
            "url": canonical_url,
            "creator": creator,
            "count": count,
            "raw": cleaned
        }

    # 6. Check if Username
    # Don't match if it has slashes or is a pure number
    if "/" not in target and not target.lstrip("@").isdigit():
        user_match = re.match(r'^@?([a-zA-Z0-9_\.]{2,30})$', target)
        if user_match:
            username = user_match.group(1)
            return {
                "type": "username",
                "creator": username,
                "count": count,
                "raw": cleaned
            }

    return {
        "type": "unknown",
        "raw": cleaned
    }

def get_user_video_urls(username: str, count: int = 3) -> List[str]:
    """
    Visits a TikTok creator profile and extracts their newest N video URLs.
    Supports up to 20 videos safely.
    """
    clean_username = username.lstrip("@").strip()
    profile_url = f"https://www.tiktok.com/@{clean_username}"

    # Safe clamp between 1 and 20
    safe_count = max(1, min(count, 20))

    ydl_opts = {
        'extract_flat': True,
        'playlistend': safe_count,
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': MOBILE_USER_AGENT
        }
    }

    video_urls = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(profile_url, download=False)
            entries = res.get('entries', []) or []
            for entry in entries:
                url = entry.get('url')
                if url:
                    video_urls.append(url)
                if len(video_urls) >= safe_count:
                    break
    except Exception as e:
        print(f"Error fetching user videos for @{clean_username}: {e}")

    return video_urls

def download_tiktok_audio_and_meta(url: str) -> Dict[str, Any]:
    """
    Downloads ONLY the audio track (.mp3) and extracts complete metadata
    (captions, hashtags, background music/trending sound, author, stats).
    Never downloads or saves video files to disk, saving massive bandwidth and time.
    """
    unique_id = uuid.uuid4().hex[:8]
    target_mp3 = os.path.join(DOWNLOADS_DIR, f"tiktok_{unique_id}_audio.mp3")

    clean_target = url.strip()
    vid = extract_video_id(clean_target)
    target_query = vid if vid else clean_target
    if target_query.isdigit() and len(target_query) >= 15:
        target_url = f"https://www.tiktok.com/@tiktok/video/{target_query}"
    elif "/video/" in clean_target and "@" not in clean_target:
        target_url = re.sub(r'tiktok\.com/video/(\d+)', r'tiktok.com/@tiktok/video/\1', clean_target)
    else:
        target_url = clean_target

    # 1. Primary engine: TikWM fast metadata & direct audio stream
    try:
        headers = {'User-Agent': DESKTOP_USER_AGENT}
        r = requests.post("https://www.tikwm.com/api/", data={"url": target_query, "hd": 1}, headers=headers, timeout=12)
        d = r.json()
        if d.get("code") == 0:
            data = d.get("data", {})
            music_url = data.get("music") or data.get("music_info", {}).get("play")
            audio_downloaded = False

            if music_url:
                try:
                    resp = requests.get(music_url, stream=True, headers=headers, timeout=20)
                    if resp.status_code == 200:
                        with open(target_mp3, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=65536):
                                if chunk:
                                    f.write(chunk)
                        if os.path.exists(target_mp3) and os.path.getsize(target_mp3) > 1000:
                            audio_downloaded = True
                except Exception:
                    audio_downloaded = False

            # If direct music stream wasn't available, extract audio directly from video stream via FFmpeg
            if not audio_downloaded:
                play_url = data.get("play") or data.get("wmplay")
                if play_url:
                    try:
                        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                        cmd = [
                            ffmpeg_exe, "-y",
                            "-headers", f"User-Agent: {DESKTOP_USER_AGENT}\r\n",
                            "-i", play_url,
                            "-vn", "-acodec", "libmp3lame", "-q:a", "4",
                            target_mp3
                        ]
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=45)
                        if os.path.exists(target_mp3) and os.path.getsize(target_mp3) > 1000:
                            audio_downloaded = True
                    except Exception as fe:
                        print(f"FFmpeg direct stream extraction failed: {fe}")

            if audio_downloaded:
                caption = data.get("title") or ""
                author = data.get("author", {})
                music_info = data.get("music_info", {})
                uid = author.get("unique_id", "")
                nickname = author.get("nickname") or uid or "Unknown Creator"

                raw_music_title = music_info.get("title") or "Original Audio"
                is_original_sound = "original" in raw_music_title.lower()

                return {
                    "success": True,
                    "url": f"https://www.tiktok.com/@{uid}/video/{vid}" if uid and vid else target_url,
                    "video_id": vid or data.get("id", ""),
                    "audio_path": target_mp3,
                    "video_path": None,  # Strictly no video downloaded
                    "caption": caption,
                    "hashtags": extract_hashtags(caption),
                    "uploader": nickname,
                    "uploader_handle": f"@{uid}" if uid else "",
                    "duration": data.get("duration", 0),
                    "stats": {
                        "views": data.get("play_count", 0),
                        "likes": data.get("digg_count", 0),
                        "comments": data.get("comment_count", 0)
                    },
                    "music": {
                        "title": raw_music_title,
                        "artist": music_info.get("author") or nickname,
                        "album": music_info.get("album", ""),
                        "is_original_sound": is_original_sound,
                        "sound_type": "Original Voice / Creator Sound" if is_original_sound else "Trending / Commercial Music Track"
                    }
                }
    except Exception as tikwm_err:
        print(f"TikWM audio extraction issue on {clean_target}: {tikwm_err}. Trying yt-dlp audio...")

    # 2. Secondary fallback engine: yt-dlp audio-only extraction
    try:
        output_template = os.path.join(DOWNLOADS_DIR, f"tiktok_{unique_id}_audio.%(ext)s")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 30,
            'http_headers': {'User-Agent': MOBILE_USER_AGENT}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            downloaded_mp3 = os.path.join(DOWNLOADS_DIR, f"tiktok_{unique_id}_audio.mp3")
            if not os.path.exists(downloaded_mp3):
                for f in os.listdir(DOWNLOADS_DIR):
                    if unique_id in f and f.endswith(".mp3"):
                        downloaded_mp3 = os.path.join(DOWNLOADS_DIR, f)
                        break

            if os.path.exists(downloaded_mp3):
                caption = info.get("description") or info.get("title") or ""
                native_tags = info.get("tags") or []
                caption_tags = extract_hashtags(caption)
                combined_tags = list(dict.fromkeys(caption_tags + [f"#{t}" if not t.startswith("#") else t for t in native_tags]))

                uploader = info.get("uploader") or info.get("creator") or info.get("uploader_id") or "Unknown Creator"
                uploader_id = info.get("uploader_id") or ""

                raw_track = info.get("track") or info.get("alt_title") or ""
                is_original_sound = not raw_track or "original" in raw_track.lower()
                music_title = raw_track or (f"Original Sound - @{uploader_id}" if uploader_id else "Original Audio")
                music_artist = info.get("artist") or uploader

                return {
                    "success": True,
                    "url": target_url,
                    "video_id": vid or info.get("id", ""),
                    "audio_path": downloaded_mp3,
                    "video_path": None,  # Strictly no video downloaded
                    "caption": caption,
                    "hashtags": combined_tags,
                    "uploader": uploader,
                    "uploader_handle": f"@{uploader_id}" if uploader_id and not uploader_id.startswith("@") else uploader_id,
                    "duration": info.get("duration", 0),
                    "stats": {
                        "views": info.get("view_count", 0),
                        "likes": info.get("like_count", 0),
                        "comments": info.get("comment_count", 0)
                    },
                    "music": {
                        "title": music_title,
                        "artist": music_artist,
                        "album": info.get("album", ""),
                        "is_original_sound": is_original_sound,
                        "sound_type": "Original Voice / Creator Sound" if is_original_sound else "Trending / Commercial Music Track"
                    }
                }
    except Exception as ydl_err:
        return {"success": False, "error": str(ydl_err), "url": url}

    return {"success": False, "error": "Could not extract audio track", "url": url}

def download_tiktok_video(url: str) -> Dict[str, Any]:
    """
    Downloads TikTok audio and metadata directly (no video file).
    Maintained for backwards compatibility.
    """
    return download_tiktok_audio_and_meta(url)
