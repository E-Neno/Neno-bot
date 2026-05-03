import os
import tempfile
import httpx
import pilk

from app.config import OPENAI_API_KEY
from app.utils.logging_utils import log_event

class VoiceASRError(Exception):
    pass

def convert_silk_to_wav(silk_path: str) -> str:
    """Converts a .silk file to a .wav file and returns the path to the temporary .wav file."""
    try:
        # Check if valid silk by getting duration
        pilk.get_duration_ms(silk_path)
    except Exception as e:
        raise VoiceASRError(f"Invalid silk file or pilk error: {e}")

    wav_fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(wav_fd)
    
    try:
        pilk.silk_to_wav(silk_path, wav_path)
        return wav_path
    except Exception as e:
        if os.path.exists(wav_path):
            os.remove(wav_path)
        raise VoiceASRError(f"Failed to convert silk to wav: {e}")

def transcribe_voice(media_path: str, trace_id: str) -> str:
    """Transcribes the given media file using OpenAI Whisper API and returns the text."""
    if not media_path or not os.path.exists(media_path):
        raise VoiceASRError(f"Voice file does not exist at path: {media_path}")
    
    if not OPENAI_API_KEY:
        log_event(
            "asr",
            "transcription_failed",
            trace_id=trace_id,
            error_type="ConfigError",
            error_message="OPENAI_API_KEY is not configured for ASR"
        )
        raise VoiceASRError("OPENAI_API_KEY is not configured for ASR")

    wav_path = None
    try:
        if media_path.lower().endswith(".silk"):
            wav_path = convert_silk_to_wav(media_path)
            file_to_send = wav_path
        else:
            file_to_send = media_path
            
        with open(file_to_send, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            data = {"model": "whisper-1"}
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    files=files,
                    data=data,
                    headers=headers
                )
                
                if response.status_code != 200:
                    raise VoiceASRError(f"ASR API returned {response.status_code}: {response.text}")
                    
                result = response.json()
                text = result.get("text", "").strip()
                
                log_event(
                    "asr",
                    "transcription_success",
                    trace_id=trace_id,
                    media_path=media_path,
                    text_len=len(text)
                )
                return text
    except Exception as e:
        log_event(
            "asr",
            "transcription_failed",
            trace_id=trace_id,
            media_path=media_path,
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise VoiceASRError(f"Transcription failed: {e}") from e
    finally:
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)
