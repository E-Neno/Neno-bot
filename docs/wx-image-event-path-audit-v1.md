# WeChat Image Event Path Audit v1

Date: 2026-05-03

## Conclusion

WeChat image messages are not lost in `getUpdates()`.

They are visible in `openclaw-weixin` monitor logs as `item_list` entries with
`type=2` (`MessageItemType.IMAGE`).

The image structure is then downgraded before `neno-bridge` sees the event.
The downgrade happens in the `processOneMessage() -> weixinMessageToMsgContext()
-> finalizeInboundContext() -> dispatchReplyFromConfig()` path, where the raw
`WeixinMessage` is converted into a generic inbound event shape with keys like:

- `content`
- `body`
- `channel`
- `sessionKey`
- `senderId`
- `isGroup`
- `timestamp`

That generic event shape no longer includes `item_list`, `raw`, `payload`, or
other original Weixin media fields unless we explicitly preserve them.

## Evidence

Observed runtime logs:

- `inbound message: ... itemTypes=2`
  This proves `getUpdates()` returned an image message.
- `neno-bridge` wx debug topKeys only show
  `["content","body","channel","sessionKey","senderId","isGroup","timestamp"]`
  and no `item_list`.
  This proves the image structure is gone before bridge inspection.

## Minimal Fix

The minimal fix applied in the local runtime patch is:

1. Add lightweight audit logs in monitor and process-message.
2. Preserve Weixin image metadata only on the dispatch context sent downstream:
   - `message_type`
   - `item_list`
   - `raw.message_id`
   - `raw.message_type`
   - `raw.item_list`
   - `attachments`

This does not change memory, relationship, or proactive logic, and does not
change the stored inbound session context.

## Runtime Files Inspected

- `/home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/monitor/monitor.ts`
- `/home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/messaging/process-message.ts`
- `/home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/messaging/inbound.ts`
- `/home/admin/.openclaw/plugins/neno-bridge/index.js`

## Repo Tracked Files Updated

- `vendor/openclaw-weixin/src/monitor/monitor.ts`
- `vendor/openclaw-weixin/src/messaging/process-message.ts`
- `openclaw-plugins/neno-bridge/index.js`
