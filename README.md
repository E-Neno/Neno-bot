# Neno Bot

Neno Bot is a local FastAPI backend for chat, memory, relationship state, platform message forwarding, QQ proactive message candidates, and WeChat image-to-text chat input.

## Start

1. Create a virtual environment and install dependencies from `requirements.txt`.
2. Copy `.env.example` to `.env` and fill in local values.
3. Run the API:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The browser test console is available at:

```text
http://127.0.0.1:8000/test
```

## Current Scope

Main supported paths:

- normal text chat
- chat memory and relationship state
- platform message forwarding
- QQ proactive message candidates
- WeChat image input -> visual understanding -> normalized text -> normal text reply

Not included in the current image route:

- voice input
- TTS
- image generation
- video

## Environment

Required local settings live in `.env`. Do not commit `.env`.

Main settings:

- `OPENROUTER_API_KEY`
- `OPENROUTER_CHAT_MODEL`
- `OPENROUTER_VISION_MODEL`
- `OPENROUTER_MEMORY_MODEL`
- `HISTORY_LIMIT`
- `MEMORY_LIMIT`
- `ADMIN_TOKEN`
- `PLATFORM_TOKEN`

QQ proactive message settings:

- `PROACTIVE_ENABLED`
- `PROACTIVE_CHECK_INTERVAL_SECONDS`
- `PROACTIVE_DAILY_LIMIT`
- `PROACTIVE_MIN_INTERVAL_MINUTES`
- `PROACTIVE_RECENT_CHAT_SKIP_MINUTES`
- `PROACTIVE_ACTIVE_START`
- `PROACTIVE_ACTIVE_END`
- `PROACTIVE_RANDOM_PROBABILITY`
- `PROACTIVE_QQ_ALLOWED_TARGET_HASHES`
- `NENO_BRIDGE_SEND_QQ_URL`

## OpenClaw Plugin

A sanitized copy of the local Neno Bridge plugin is included at:

```text
openclaw-plugins/neno-bridge/
```

The real allowlist files are intentionally excluded:

- `allowed_qq_users.json`
- `allowed_wx_users.json`

Use the included example files as templates:

- `allowed_qq_users.example.json`
- `allowed_wx_users.example.json`

Do not commit OpenClaw runtime configuration, local identity files, allowlists, or account state.

## Image Input Notes

The current WeChat image route uses:

1. upstream WeChat image event
2. preserved image attachment metadata
3. local `media_path`
4. local file read
5. base64 `data:` URL
6. OpenRouter multimodal
7. normalized text passed into the existing chat main chain

This route does not rely on using the upstream WeChat attachment URL directly as the final multimodal provider input.

Related notes:

- `docs/wx-image-event-path-audit-v1.md`
- `docs/wx-image-input-route-v1_1.md`
- `docs/openclaw-weixin-local-patch.md`
