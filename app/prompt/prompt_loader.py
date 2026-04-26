from pathlib import Path


def load_text(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return file_path.read_text(encoding="utf-8").strip()