# WeChat Image Input Route v1.1

Date: 2026-05-03

## Supported Scope

Current supported range is:

- WeChat image input
- Visual model understanding
- Normalized text passed into the existing chat main chain
- Normal text reply returned to the user

Not included in this route:

- voice input
- TTS
- image generation
- video

## Current Route

The image input path is:

1. Upstream WeChat image event reaches `openclaw-weixin`.
2. Bridge preserves image metadata on the downstream event.
3. Neno receives `attachments` with `media_path` for the local image file.
4. Backend reads the local file from disk.
5. File bytes are converted to a base64 `data:` URL.
6. The base64 image is sent to OpenRouter multimodal.
7. Visual output is normalized into stable text for the chat main chain.
8. Existing `run_chat_turn()` continues as plain text chat.

## Why Not Use The WeChat Attachment URL Directly

We do not rely on the raw WeChat attachment URL as the primary multimodal input
for two reasons:

- The WeChat-side dispatch data is not a stable, direct, provider-ready image
  URL for OpenRouter. The useful image payload is preserved locally through the
  patched bridge path, not as a guaranteed remote public URL.
- The local `media_path` is the asset Neno can actually read at reply time. It
  avoids depending on upstream URL lifetime, accessibility, and provider-side
  fetch behavior.

## Why The Final Choice Is Local File To Base64

The local file to base64 route is the most reliable current path because:

- the image is already available on disk
- the backend fully controls the payload sent to OpenRouter
- it avoids remote fetch failures caused by expired, private, or unreachable
  upstream URLs
- the route is easy to audit end to end

## Operational Notes

- Multimodal audit logs should be enough to answer:
  - did an image attachment reach the backend
  - did multimodal normalization start
  - did normalization succeed or fail
- The normalized text must keep the fact that the user already sent an image.
- If multimodal understanding fails, the user-facing message should stay
  natural and should not expose provider internals.
