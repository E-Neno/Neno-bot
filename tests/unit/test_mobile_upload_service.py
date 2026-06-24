from __future__ import annotations

import os

import pytest

from app.services import mobile_upload_service as service


def test_save_mobile_upload_rejects_oversized_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setitem(service.MAX_UPLOAD_BYTES, "file", 4)

    with pytest.raises(service.MobileUploadError, match="upload too large"):
        service.save_mobile_upload(
            content=b"12345",
            kind="file",
            filename="note.txt",
            mime_type="text/plain",
        )


def test_save_mobile_upload_prunes_old_files(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(service, "MAX_UPLOAD_FILES_PER_KIND", 2, raising=False)
    kind_dir = tmp_path / "file"
    kind_dir.mkdir(parents=True)
    for index in range(3):
        old = kind_dir / f"old-{index}.txt"
        old.write_text(f"old {index}", encoding="utf-8")
        os.utime(old, (100 + index, 100 + index))

    attachment = service.save_mobile_upload(
        content=b"new",
        kind="file",
        filename="new.txt",
        mime_type="text/plain",
    )

    remaining = sorted(path.name for path in kind_dir.iterdir())
    assert len(remaining) == 2
    assert attachment.media_path is not None
    assert attachment.media_path.endswith(".txt")
    assert any(path.name in remaining for path in [kind_dir / attachment.media_path])
    assert "old-0.txt" not in remaining
