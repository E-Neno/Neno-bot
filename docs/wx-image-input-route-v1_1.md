# WeChat Image Input Route v1.2

Date: 2026-07-07

## Supported Scope

Current supported range is:

- WeChat image input with local `media_path`
- Permanent visual asset archival
- Text projection stored in the chat history
- Current-turn image block passed to the main multimodal chat model
- Caption-only normalization retained as fallback when visual memory is disabled or archival fails

Not included in this route:

- voice input
- TTS
- image generation
- video
- automatic replay of old image bytes into every future prompt

## Current Route

The preferred image input path is:

1. Upstream WeChat image event reaches `openclaw-weixin`.
2. Bridge preserves image metadata on the downstream event.
3. Neno receives `attachments` with `media_path` for the local image file.
4. If `VISUAL_MEMORY_ENABLED=true`, backend archives the local file into `data/visual_assets`.
5. `messages.content` receives only a text projection, for example:

   ```text
   [用户发送了一张图片]
   用户附带文字：...
   visual_asset_id: vimg_...
   ```

6. `run_chat_turn()` resolves the current turn asset to an image block after history and dynamic context.
7. The main chat model receives the current image and text together.
8. Existing memory, relationship, digest, preview, and world-intent paths continue to see only the text projection.

If archival cannot be used, the old route remains available:

```text
image attachment -> multimodal caption -> normalized text -> plain text chat turn
```

## Why Not Use The WeChat Attachment URL Directly

We do not rely on the raw WeChat attachment URL as the primary multimodal input because:

- The WeChat-side dispatch data is not a stable, direct, provider-ready image URL for OpenRouter.
- The useful image payload is preserved locally through the patched bridge path.
- The permanent asset store can dedupe by SHA-256 and survive mobile upload pruning.

## Persistence Boundary

The system follows `Text-Persistent, Multimodal-Live Turn`:

- SQLite `messages.content` stores text projection only.
- `metadata_json` stores `asset_uid` and image metadata, never base64 or `data:image/...`.
- Current-turn image blocks are temporary prompt input, not historical prompt content.
- Historical images are recalled through `visual_memory.search` and `visual_memory.inspect`.

## Operational Notes

- Multimodal audit logs should answer:
  - did an image attachment reach the backend
  - was it archived into visual memory
  - did the current turn request include an image block
  - did fallback caption normalization run
- If visual memory archival fails, user-facing behavior should degrade naturally through the existing caption fallback.
- Visual recall observations are append-only rows in `visual_observations`; they must not retroactively mutate old message metadata.
