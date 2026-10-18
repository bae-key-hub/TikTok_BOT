import os
import re
import uuid
from typing import Dict, Any, List, Optional, Tuple
import requests
import yt_dlp

from config import DOWNLOADS_DIR

# Robust regex matching all TikTok video, photo, short URL, and profile variations
TIKTOK_URL_REGEX = re.compile(
    r'(https?://)?(www\.|vm\.|vt\.|m\.)?tiktok\.com/[^\s]+',
    re.IGNORECASE
)

# Detects username with optional count (e.g. "@adonaymada" or "@adonaymada 5" or "adonaymada 10")
USERNAME_REGEX = re.compile(
    r'^@?([a-zA-Z0-9_\.]{2,30})(?:\s+(\d+))?$',
    re.IGNORECASE
)

MOBILE_USER_AGENT = (
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
    'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
)

def is_tiktok_url(url: str) -> bool:
    """Checks if a string contains or looks like a valid TikTok link."""
    return bool(TIKTOK_URL_REGEX.search(url))

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
    Extracts the creator username from a TikTok link (video, profile, or short link).
    """
    if not url:
        return None

    # 1. Direct match in URL (e.g. tiktok.com/@adonaymada/...)
    m = re.search(r'tiktok\.com/@([a-zA-Z0-9_\.]+)', url, re.IGNORECASE)
    if m:
        return m.group(1).rstrip('/')

    # 2. If short URL (vm.tiktok.com, vt.tiktok.com, /t/), follow HTTP redirect
    if any(domain in url.lower() for domain in ['vm.tiktok.com', 'vt.tiktok.com', '/t/']):
        try:
            headers = {'User-Agent': MOBILE_USER_AGENT}
            resp = requests.head(url, headers=headers, allow_redirects=True, timeout=6)
            final_url = resp.url
            m = re.search(r'tiktok\.com/@([a-zA-Z0-9_\.]+)', final_url, re.IGNORECASE)
            if m:
                return m.group(1).rstrip('/')
        except Exception:
            pass

    # 3. Fallback: Query TikWM metadata
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.post("https://www.tikwm.com/api/", data={"url": url}, headers=headers, timeout=6)
        d = r.json()
        if d.get("code") == 0:
            uid = d.get("data", {}).get("author", {}).get("unique_id")
            if uid:
                return uid
    except Exception:
        pass

    return None

def parse_any_query(text: str) -> Dict[str, Any]:
    """
    Parses user input into structured intent:
    - pure number: "4", "10"
    - video link with optional count: "https://... 5"
    - profile link with optional count: "https://tiktok.com/@user 3"
    - username with optional count: "@adonaymada" or "@adonaymada 10"
    """
    cleaned = text.strip()

    # 1. Pure number
    if cleaned.isdigit():
        return {
            "type": "number",
            "count": int(cleaned),
            "raw": cleaned
        }

    # 2. Extract potential trailing count (e.g. "... 5")
    parts = cleaned.rsplit(maxsplit=1)
    target = cleaned
    count = None
    if len(parts) == 2 and parts[1].isdigit():
        target = parts[0].strip()
        count = int(parts[1])

    # 3. Check if TikTok URL
    if is_tiktok_url(target) or "tiktok.com" in target.lower():
        words = target.split()
        target_url = next((w for w in words if "tiktok.com" in w), target)
        creator = resolve_creator_from_url(target_url)
        is_single_video = any(k in target_url.lower() for k in ["/video/", "/photo/", "vm.tiktok.com", "vt.tiktok.com", "/t/"])
        return {
            "type": "video_url" if is_single_video else "profile_url",
            "url": target_url,
            "creator": creator,
            "count": count,
            "raw": cleaned
        }

    # 4. Check if Username
    # Don't match if it has slashes
    if "/" not in target:
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

def download_via_tikwm(url: str, output_path: str) -> Optional[Dict[str, Any]]:
    """
    Fast direct-stream fallback via TikWM public API.
    Downloads unwatermarked video and extracts full metadata.
    """
    try:
        api_url = "https://www.tikwm.com/api/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.post(api_url, data={"url": url, "hd": 1}, headers=headers, timeout=12)
        d = r.json()
        if d.get("code") != 0:
            return {"success": False, "error": d.get("msg", "TikWM API error")}

        data = d.get("data", {})
        play_url = data.get("play") or data.get("wmplay")
        if not play_url:
            return {"success": False, "error": "No streamable play URL returned"}

        resp = requests.get(play_url, stream=True, headers=headers, timeout=25)
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        caption = data.get("title") or ""
        author = data.get("author", {})
        music_info = data.get("music_info", {})
        uid = author.get("unique_id", "")
        nickname = author.get("nickname") or uid or "Unknown Creator"

        raw_music_title = music_info.get("title") or "Original Audio"
        is_original_sound = "original" in raw_music_title.lower()

        return {
            "success": True,
            "url": url,
            "video_path": output_path,
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
                "album": "",
                "is_original_sound": is_original_sound,
                "sound_type": "Original Voice / Creator Sound" if is_original_sound else "Trending / Commercial Music Track"
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def download_tiktok_video(url: str) -> Dict[str, Any]:
    """
    Downloads a TikTok video and extracts native metadata.
    Tries yt-dlp first, then automatically falls back to TikWM API for 100% reliability.
    """
    unique_id = uuid.uuid4().hex[:8]
    output_template = os.path.join(DOWNLOADS_DIR, f"tiktok_{unique_id}.%(ext)s")
    target_mp4 = os.path.join(DOWNLOADS_DIR, f"tiktok_{unique_id}.mp4")

    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': 30,
    }

    info = None
    downloaded_filepath = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_filepath = ydl.prepare_filename(info)
            if not os.path.exists(downloaded_filepath):
                base, _ = os.path.splitext(downloaded_filepath)
                if os.path.exists(base + ".mp4"):
                    downloaded_filepath = base + ".mp4"
    except Exception as ydl_err:
        print(f"yt-dlp issue on {url}: {ydl_err}. Triggering TikWM fallback...")
        tikwm_res = download_via_tikwm(url, target_mp4)
        if tikwm_res and tikwm_res.get("success"):
            return tikwm_res
        return {"success": False, "error": str(ydl_err), "url": url}

    if not downloaded_filepath or not os.path.exists(downloaded_filepath):
        # Secondary fallback
        tikwm_res = download_via_tikwm(url, target_mp4)
        if tikwm_res and tikwm_res.get("success"):
            return tikwm_res
        return {"success": False, "error": "Downloaded file not found", "url": url}

    # Caption
    caption = info.get("description") or info.get("title") or ""

    # Hashtags
    native_tags = info.get("tags") or []
    caption_tags = extract_hashtags(caption)

    combined_tags = []
    seen = set()
    for t in caption_tags + [f"#{t}" if not t.startswith("#") else t for t in native_tags]:
        clean_tag = t.strip()
        if clean_tag and clean_tag.lower() not in seen:
            seen.add(clean_tag.lower())
            combined_tags.append(clean_tag)

    # Uploader info
    uploader = info.get("uploader") or info.get("creator") or info.get("uploader_id") or "Unknown Creator"
    uploader_id = info.get("uploader_id") or ""

    # Duration & Metrics
    duration = info.get("duration") or 0
    like_count = info.get("like_count") or 0
    view_count = info.get("view_count") or 0
    comment_count = info.get("comment_count") or 0

    # Background Music & Trend Audio detection
    raw_track = info.get("track") or info.get("alt_title") or ""
    raw_artist = info.get("artist") or info.get("creator") or ""
    album = info.get("album") or ""

    is_original_sound = False
    if not raw_track or "original sound" in raw_track.lower() or "original audio" in raw_track.lower():
        is_original_sound = True
        music_title = f"Original Sound - @{uploader_id}" if uploader_id else "Original Audio"
        music_artist = uploader
    else:
        music_title = raw_track
        music_artist = raw_artist or uploader

    return {
        "success": True,
        "url": url,
        "video_path": downloaded_filepath,
        "caption": caption,
        "hashtags": combined_tags,
        "uploader": uploader,
        "uploader_handle": f"@{uploader_id}" if uploader_id and not uploader_id.startswith("@") else uploader_id,
        "duration": duration,
        "stats": {
            "views": view_count,
            "likes": like_count,
            "comments": comment_count
        },
        "music": {
            "title": music_title,
            "artist": music_artist,
            "album": album,
            "is_original_sound": is_original_sound,
            "sound_type": "Original Voice / Creator Sound" if is_original_sound else "Trending / Commercial Music Track"
        }
    }
