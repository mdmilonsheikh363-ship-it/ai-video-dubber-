import os
import uuid
import asyncio
import shutil
import subprocess
from pathlib import Path

import edge_tts
import whisper

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from deep_translator import GoogleTranslator


# =========================
# Flask App
# =========================

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# =========================
# Whisper Model
# =========================

whisper_model = None


def get_whisper_model():
    global whisper_model

    if whisper_model is None:
        print("Loading Whisper AI model...")
        whisper_model = whisper.load_model("tiny")
        print("Whisper model loaded.")

    return whisper_model


# =========================
# TTS Voice Mapping
# =========================

VOICE_MAP = {
    "bn": "bn-BD-NabanitaNeural",
    "en": "en-US-AvaNeural",
    "hi": "hi-IN-SwaraNeural",
    "ta": "ta-IN-PallaviNeural",
    "te": "te-IN-ShrutiNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "id": "id-ID-GadisNeural",
    "th": "th-TH-PremwadeeNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "tr": "tr-TR-EmelNeural",
    "pl": "pl-PL-ZofiaNeural",
    "nl": "nl-NL-ColetteNeural",
    "uk": "uk-UA-PolinaNeural",
    "ar": "ar-SA-ZariyahNeural",
    "he": "he-IL-HilaNeural",
}


def get_voice(language_code):
    language_code = language_code.lower()

    if language_code in VOICE_MAP:
        return VOICE_MAP[language_code]

    return "en-US-AvaNeural"


# =========================
# Health Check
# =========================

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "message": "AI Video Dubber Server is Live!",
        "endpoint": "/dubbing"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy"
    })


# =========================
# FFmpeg Helper
# =========================

def run_ffmpeg(command):
    print("Running FFmpeg:")

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(
            "FFmpeg error: " + result.stderr[-3000:]
        )

    return result


# =========================
# Generate TTS
# =========================

async def generate_tts(text, voice, output_path):

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice
    )

    await communicate.save(str(output_path))


# =========================
# Dubbing API
# =========================

@app.route("/dubbing", methods=["POST"])
def dub_video():

    job_id = uuid.uuid4().hex

    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id

    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)

    try:

        # -------------------------
        # Check video
        # -------------------------

        if "video" not in request.files:
            return jsonify({
                "error": "No video file found."
            }), 400

        video_file = request.files["video"]

        if not video_file.filename:
            return jsonify({
                "error": "Invalid video file."
            }), 400


        # -------------------------
        # Form values
        # -------------------------

        source_lang = request.form.get(
            "source_lang",
            "auto"
        )

        target_lang = request.form.get(
            "target_lang",
            "bn-BD"
        )

        enable_subtitle = (
            request.form.get(
                "enable_subtitle",
                "true"
            ).lower() == "true"
        )

        enable_lipsync = (
            request.form.get(
                "enable_lipsync",
                "true"
            ).lower() == "true"
        )


        target_code = target_lang.split("-")[0]


        # -------------------------
        # Save uploaded video
        # -------------------------

        original_name = Path(
            video_file.filename
        ).name

        input_path = job_upload_dir / original_name

        video_file.save(str(input_path))

        print("Video uploaded:", input_path)


        # -------------------------
        # Extract audio
        # -------------------------

        audio_path = job_upload_dir / "audio.wav"

        run_ffmpeg([
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path)
        ])


        # -------------------------
        # Whisper Transcription
        # -------------------------

        model = get_whisper_model()

        whisper_language = None

        if source_lang != "auto":
            whisper_language = source_lang.split("-")[0]

        print("Transcribing video...")

        if whisper_language:
            result = model.transcribe(
                str(audio_path),
                language=whisper_language
            )
        else:
            result = model.transcribe(
                str(audio_path)
            )

        original_text = result.get(
            "text",
            ""
        ).strip()

        print("Original text:", original_text)


        if not original_text:
            return jsonify({
                "error": "No speech detected in the video."
            }), 400


        # -------------------------
        # Translation
        # -------------------------

        print(
            "Translating to:",
            target_code
        )

        translated_text = GoogleTranslator(
            source="auto",
            target=target_code
        ).translate(original_text)

        print(
            "Translated text:",
            translated_text
        )


        # -------------------------
        # Text To Speech
        # -------------------------

        voice = get_voice(target_code)

        dubbed_audio_path = (
            job_output_dir / "dubbed_audio.mp3"
        )

        print(
            "Generating voice:",
            voice
        )

        asyncio.run(
            generate_tts(
                translated_text,
                voice,
                dubbed_audio_path
            )
        )


        # -------------------------
        # Create final video
        # -------------------------

        output_path = (
            job_output_dir /
            f"dubbed_{original_name}"
        )


        # Note:
        # enable_lipsync is accepted from frontend.
        # Actual AI lip-sync is not performed here yet.

        print("Creating final video...")


        run_ffmpeg([
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-i",
            str(dubbed_audio_path),

            "-map",
            "0:v:0",
            "-map",
            "1:a:0",

            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",

            "-c:a",
            "aac",
            "-b:a",
            "128k",

            "-shortest",

            str(output_path)
        ])


        print(
            "Final video created:",
            output_path
        )


        # -------------------------
        # Send video
        # -------------------------

        response = send_file(
            str(output_path),
            mimetype="video/mp4",
            as_attachment=True,
            download_name=f"dubbed_{original_name}"
        )


        # -------------------------
        # Cleanup after response
        # -------------------------

        @response.call_on_close
        def cleanup():

            try:
                shutil.rmtree(
                    job_upload_dir,
                    ignore_errors=True
                )

                shutil.rmtree(
                    job_output_dir,
                    ignore_errors=True
                )

                print(
                    "Temporary files cleaned."
                )

            except Exception as cleanup_error:

                print(
                    "Cleanup error:",
                    cleanup_error
                )


        return response


    except Exception as e:

        print(
            "ERROR:",
            repr(e)
        )

        return jsonify({
            "error": str(e)
        }), 500


# =========================
# Start Server
# =========================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
