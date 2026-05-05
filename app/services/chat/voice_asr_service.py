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

def _is_silk_file(file_path: str) -> bool:
    if file_path.lower().endswith(".silk"):
        return True

    try:
        with open(file_path, "rb") as f:
            header = f.read(10)
            return header.startswith(b"#!SILK_V3") or header.startswith(b"\x02#!SILK_V3")
    except Exception:
        return False

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
        messages=messages,
        language="zh",
        enable_lid=False,
        enable_itn=True
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

def get_audio_metadata(file_path: str) -> dict:
    metadata = {
        "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        "duration_ms": 0,
        "sample_rate": 0,
        "channels": 0
    }
    try:
        import wave
        with wave.open(file_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            metadata["sample_rate"] = rate
            metadata["channels"] = wf.getnchannels()
            if rate > 0:
                metadata["duration_ms"] = int((frames / float(rate)) * 1000)
    except Exception as e:
        # wave module is strict; if it fails, we still have file_size
        # we log this internally if needed, but don't crash
        pass
    return metadata

def transcribe_voice(media_path: str, trace_id: str) -> str:
    """Transcribes the given media file using configured ASR provider and returns the text."""
    if not media_path or not os.path.exists(media_path):
        raise VoiceASRError(f"Voice file does not exist at path: {media_path}")
    
    wav_path = None
    file_to_send = media_path
    duration_ms = 0
    
    try:
        if _is_silk_file(media_path):
            try:
                duration_ms = pilk.get_duration(media_path)
            except Exception:
                pass
            wav_path = convert_silk_to_wav(media_path)
            file_to_send = wav_path
            
        metadata = get_audio_metadata(file_to_send)
        # Use silk duration if available as it's more reliable than wave module parsing
        if duration_ms == 0:
            duration_ms = metadata["duration_ms"]
            
        log_event(
            "asr",
            "audio_preprocessing",
            trace_id=trace_id,
            wav_path=file_to_send,
            file_size=metadata["file_size"],
            duration_ms=duration_ms,
            sample_rate=metadata["sample_rate"],
            channels=metadata["channels"],
            provider=ASR_PROVIDER
        )
            
        if ASR_PROVIDER == "dashscope_qwen":
            text = _transcribe_with_dashscope(file_to_send, trace_id)
        else:
            text = _transcribe_with_whisper(file_to_send, trace_id)
            
        text_len = len(text)
        log_event(
            "asr",
            "transcription_success",
            trace_id=trace_id,
            provider=ASR_PROVIDER,
            media_path=media_path,
            text_len=text_len
        )
        
        if duration_ms > 1500 and text_len <= 2:
            log_event(
                "asr",
                "transcription_suspect_short_result",
                trace_id=trace_id,
                duration_ms=duration_ms,
                text=text,
                text_len=text_len
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
        # Handle ASR_DEBUG_KEEP_WAV
        if os.environ.get("ASR_DEBUG_KEEP_WAV") == "1":
            import shutil
            # Use a user-specific directory to avoid permission issues if root created the default one
            debug_dir = "/tmp/neno-asr-debug-admin"
            try:
                os.makedirs(debug_dir, exist_ok=True)
                debug_path = os.path.join(debug_dir, f"{trace_id}.wav")
                # If we have a converted wav, keep it. If not, keep the original.
                file_to_keep = file_to_send
                shutil.copy2(file_to_keep, debug_path)
                log_event("asr", "debug_kept_wav", trace_id=trace_id, path=debug_path)
            except Exception as e:
                log_event("asr", "debug_keep_failed", trace_id=trace_id, error=str(e), debug_dir=debug_dir)
        
        # Only remove if it's a temporary converted file
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)
