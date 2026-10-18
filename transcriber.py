import os
import json
import time
from typing import Dict, Any, Optional
from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

CANDIDATE_MODELS = [
    GEMINI_MODEL,
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.6-flash"
]

def transcribe_and_translate_to_amharic(media_path: str, original_caption: str = "") -> Dict[str, Any]:
    """
    Takes an audio or video file + the original caption:
    1. Transcribes speech and translates to Amharic.
    2. Translates the video's original caption to Amharic.
    3. Analyzes background audio/music to identify trending audio or vibes.
    4. Generates Amharic summary & key points.
    """
    if not os.path.exists(media_path):
        return {
            "success": False,
            "error": f"File not found: {media_path}"
        }

    client = genai.Client(api_key=GEMINI_API_KEY)

    uploaded_file = None
    try:
        print(f"Uploading {media_path} to Gemini...")
        uploaded_file = client.files.upload(file=media_path)
        
        # Wait until file is processed
        max_wait = 60
        waited = 0
        while uploaded_file.state.name == "PROCESSING" and waited < max_wait:
            time.sleep(2)
            waited += 2
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name != "ACTIVE":
            return {
                "success": False,
                "error": f"File processing failed with state: {uploaded_file.state.name}"
            }

        caption_context = f'The original TikTok caption written by the creator is: "{original_caption}"\n' if original_caption else ""

        prompt = (
            "You are an expert audio analyst, speech transcriber, and Amharic (አማርኛ) translator.\n"
            f"{caption_context}"
            "Please analyze the audio in this file carefully and perform the following tasks:\n\n"
            "1. SPEECH TRANSCRIPTION & TRANSLATION:\n"
            "   - Detect the language spoken.\n"
            "   - Transcribe the exact original spoken words.\n"
            "   - Translate the spoken transcript into natural, fluent Amharic (አማርኛ) written in Ge'ez script (ፊደል).\n"
            "   - If the speech is ALREADY in Amharic, provide the exact transcription in Ge'ez script.\n\n"
            "2. CAPTION TRANSLATION:\n"
            "   - Translate the original TikTok caption into natural Amharic (አማርኛ) in Ge'ez script.\n"
            "   - If there was no caption or it is empty, set this to 'ምንም መግለጫ አልተገኘም'.\n\n"
            "3. BACKGROUND MUSIC & SOUND ANALYSIS:\n"
            "   - Identify if there is background music, a trending TikTok audio/sound, ambient noise, or pure voiceover.\n"
            "   - Describe the sound vibe/genre (e.g. 'Upbeat trending pop beat', 'Afrobeats rhythm', 'Sad piano', 'Voiceover with silence').\n\n"
            "4. SUMMARY & KEY TAKEAWAYS:\n"
            "   - Provide an Amharic summary (አጭር ማጠቃለያ) in 2-3 sentences.\n"
            "   - Provide 2-4 key takeaways (ዋና ዋና ነጥቦች) in Amharic as a list of bullet points.\n\n"
            "Respond ONLY with a JSON object with this exact structure:\n"
            "{\n"
            '  "original_language": "Language Name (e.g. English, Amharic, etc.)",\n'
            '  "original_transcript": "Exact transcription in original language",\n'
            '  "amharic_transcript": "ሙሉ የተገለበጠው ወይም የተተረጎመው የንግግር ጽሑፍ በአማርኛ ፊደል",\n'
            '  "amharic_caption_translation": "የመጀመሪያው የቲክቶክ መግለጫ (Caption) ወደ አማርኛ የተተረጎመው",\n'
            '  "sound_analysis": {\n'
            '    "has_background_music": true,\n'
            '    "sound_vibe": "Description of background sound/music"\n'
            '  },\n'
            '  "amharic_summary": "አጭር ማጠቃለያ በአማርኛ",\n'
            '  "amharic_key_points": ["ነጥብ 1", "ነጥብ 2"]\n'
            "}"
        )

        last_error = None
        for model_name in CANDIDATE_MODELS:
            try:
                print(f"Querying Gemini model: {model_name}...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=[uploaded_file, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                if response.text:
                    parsed_json = json.loads(response.text)
                    return {
                        "success": True,
                        "model_used": model_name,
                        "data": parsed_json
                    }
            except Exception as ex:
                print(f"Model {model_name} error: {ex}, trying fallback...")
                last_error = ex
                continue

        return {
            "success": False,
            "error": f"All Gemini models failed. Last error: {last_error}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
