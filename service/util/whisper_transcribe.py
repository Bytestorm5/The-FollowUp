import os
import tempfile
import subprocess
import logging
import torch
import whisper
import yt_dlp

LOGGER = logging.getLogger(__name__)

# Load model once
MODEL = None

def get_whisper_model():
    global MODEL
    if MODEL is None:
        device = 'cpu'  # Force CPU as requested
        MODEL = whisper.load_model('base', device=device)  # Use 'base' for balance of speed and accuracy
    return MODEL

def extract_whisper_text(url: str) -> str:
    """Extract text from YouTube video using Whisper transcription."""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp()
        audio_path = download_audio(url, temp_dir)
        text = transcribe_audio(audio_path)
        return text
    except Exception as exc:
        LOGGER.warning("Whisper transcription failed for %s err=%s", url, exc)
        return ""
    finally:
        if temp_dir:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

def download_audio(url: str, temp_dir: str) -> str:
    """Download audio from YouTube URL and return path to wav file."""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        audio_file = os.path.join(temp_dir, f"{info['id']}.wav")
        return audio_file

def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file using Whisper."""
    model = get_whisper_model()
    result = model.transcribe(audio_path, language='en')  # Assume English for now
    return result['text'].strip()