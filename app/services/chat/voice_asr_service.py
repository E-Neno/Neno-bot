import os
import tempfile
import httpx
import pilk
import dashscope

from app.config import (
    OPENAI_API_KEY, ASR_PROVIDER, DASHSCOPE_API_KEY, DASHSCOPE_ASR_MODEL
)
from app.utils.logging_utils import log_event

class VoiceASRError(Exception):
    pass

def convert_silk_to_wav(silk_path: str) -> str:
    """Converts a .silk file to a .wav file and returns the path to the temporary .wav file."""
    try:
        # Check if valid silk by getting duration
        pilk.get_duration(silk_path)
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

def _transcribe_with_whisper(wav_path: str, trace_id: str) -> str:
    if not OPENAI_API_KEY:
        raise VoiceASRError("OPENAI_API_KEY is not configured for ASR")

    with open(wav_path, "rb") as f:
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
            return result.get("text", "").strip()

def _transcribe_with_dashscope(wav_path: str, trace_id: str) -> str:
    if not DASHSCOPE_API_KEY:
        raise VoiceASRError("DASHSCOPE_API_KEY is not configured for ASR")

    dashscope.api_key = DASHSCOPE_API_KEY
    abs_path = os.path.abspath(wav_path)
    file_uri = f"file://{abs_path}"
    
    messages = [
        {
            "role": "user",
            "content": [{"audio": file_uri}]
        }
    ]
    
    response = dashscope.MultiModalConversation.call(
        model=DASHSCOPE_ASR_MODEL,
        messages=messages
    )
    
    if response.status_code == 200:
        try:
            choices = response.output.choices
            if choices and choices[0].message and choices[0].message.content:
                content = choices[0].message.content
                if isinstance(content, list):
                    texts = [item.get("text", "") for item in content if "text" in item]
                    return "".join(texts).strip()
                elif isinstance(content, str):
                    return content.strip()
            return ""
        except Exception as e:
            raise VoiceASRError(f"Failed to parse DashScope response: {response}")
    else:
        raise VoiceASRError(f"DashScope ASR returned {response.status_code}: {response.message}")

def transcribe_voice(media_path: str, trace_id: str) -> str:
    """Transcribes the given media file using configured ASR provider and returns the text."""
    if not media_path or not os.path.exists(media_path):
        raise VoiceASRError(f"Voice file does not exist at path: {media_path}")
    
    wav_path = None
    try:
        if media_path.lower().endswith(".silk"):
            wav_path = convert_silk_to_wav(media_path)
            file_to_send = wav_path
        else:
            file_to_send = media_path
            
        if ASR_PROVIDER == "dashscope_qwen":
            text = _transcribe_with_dashscope(file_to_send, trace_id)
        else:
            text = _transcribe_with_whisper(file_to_send, trace_id)
            
        log_event(
            "asr",
            "transcription_success",
            trace_id=trace_id,
            provider=ASR_PROVIDER,
            media_path=media_path,
            text_len=len(text)
        )
        return text
    except Exception as e:
        log_event(
            "asr",
            "transcription_failed",
            trace_id=trace_id,
            provider=ASR_PROVIDER,
            media_path=media_path,
            error_type=type(e).__name__,
            error_message=str(e)
        )
        raise VoiceASRError(f"Transcription failed: {e}") from e
    finally:
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)
