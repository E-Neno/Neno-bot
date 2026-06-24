from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from app.schemas import MediaAttachment


MAX_FILE_TEXT_CHARS = 4000
TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".log",
}


class MobileFileParseError(RuntimeError):
    pass


def parse_file_attachment(attachment: MediaAttachment) -> str:
    path = Path((attachment.media_path or "").strip())
    if not path.is_file():
        raise MobileFileParseError("file attachment missing")

    filename = (attachment.text_hint or path.name).strip() or path.name
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or (attachment.mime_type or "").startswith("text/"):
        content = _read_text(path)
    elif suffix == ".docx":
        content = _read_docx(path)
    elif suffix == ".pdf":
        content = _read_pdf(path)
    else:
        raise MobileFileParseError("unsupported file type")

    content = _compact(content)
    if not content:
        raise MobileFileParseError("file has no readable text")

    return f"[用户发送了一个文件：{filename}]\n文件内容：{truncate_file_text(content)}"


def truncate_file_text(text: str, limit: int = MAX_FILE_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as docx:
            xml = docx.read("word/document.xml")
    except Exception as exc:
        raise MobileFileParseError("docx parse failed") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise MobileFileParseError("docx xml parse failed") from exc

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in para.findall(".//w:t", ns)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise MobileFileParseError("pdf parser is not installed") from exc

    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise MobileFileParseError("pdf parse failed") from exc


def _compact(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()
