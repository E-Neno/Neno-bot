from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

import app.security as security


@dataclass
class _Client:
    host: str


class _Request:
    def __init__(self, host: str) -> None:
        self.client = _Client(host)


def test_platform_token_rejects_remote_request_when_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(security, "PLATFORM_TOKEN", "")

    with pytest.raises(HTTPException) as exc:
        security.require_platform_token(_Request("192.0.2.10"))

    assert exc.value.status_code == 403
    assert exc.value.detail == "PLATFORM_TOKEN not configured"


def test_platform_token_keeps_loopback_bypass_when_token_is_not_configured(monkeypatch):
    monkeypatch.setattr(security, "PLATFORM_TOKEN", "")

    security.require_platform_token(_Request("127.0.0.1"))


def test_platform_token_accepts_matching_remote_token(monkeypatch):
    monkeypatch.setattr(security, "PLATFORM_TOKEN", "secret-token")

    security.require_platform_token(_Request("192.0.2.10"), x_platform_token="secret-token")
