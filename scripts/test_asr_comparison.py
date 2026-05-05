import sys
import os
import time
from dotenv import load_dotenv

# Load env before importing app modules
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.chat.voice_asr_service import _transcribe_with_dashscope, _transcribe_with_whisper, get_audio_metadata

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_asr_comparison.py <path_to_wav>")
        sys.exit(1)
        
    wav_path = sys.argv[1]
    if not os.path.exists(wav_path):
        print(f"File not found: {wav_path}")
        sys.exit(1)

    print(f"=== ASR Comparison ===")
    print(f"Input file: {wav_path}")
    
    metadata = get_audio_metadata(wav_path)
    print(f"Audio metadata: {metadata}")
    print("-" * 40)

    trace_id = "test_comparison_trace"

    # Test DashScope Qwen
    print("Running DashScope Qwen...")
    start_time = time.time()
    try:
        dashscope_result = _transcribe_with_dashscope(wav_path, trace_id)
        dashscope_time = time.time() - start_time
        print(f"DashScope Result ({len(dashscope_result)} chars): {dashscope_result}")
        print(f"DashScope Time: {dashscope_time:.2f}s")
    except Exception as e:
        print(f"DashScope failed: {e}")

    print("-" * 40)

    # Test Whisper
    print("Running OpenAI Whisper...")
    start_time = time.time()
    try:
        whisper_result = _transcribe_with_whisper(wav_path, trace_id)
        whisper_time = time.time() - start_time
        print(f"Whisper Result ({len(whisper_result)} chars): {whisper_result}")
        print(f"Whisper Time: {whisper_time:.2f}s")
    except Exception as e:
        print(f"Whisper failed: {e}")

    print("======================")

if __name__ == "__main__":
    main()