# OpenClaw Weixin Local Patch

This repository tracks a local runtime patch for the OpenClaw Weixin channel
plugin so the change is not only stored under the machine-local OpenClaw
installation.

Runtime file:

```text
/home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/monitor/monitor.ts
/home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/messaging/process-message.ts
```

Tracked copies:

```text
vendor/openclaw-weixin/src/monitor/monitor.ts
vendor/openclaw-weixin/src/messaging/process-message.ts
```

Purpose:

- Bridge-layer burst merge for Weixin private text messages.
- Buffer private text messages before `processOneMessage()`.
- Merge up to 5 messages in a 7 second window with newline separators.
- Store burst buffer entries with sortable message metadata.
- Sort buffered entries before flush using `create_time_ms`, `create_time`, `seq`,
  `message_id`, then insertion order.
- Emit temporary diagnostic logs for burst ordering:
  `bridge_burst_started_sort_fields`, `bridge_burst_appended_sort_fields`, and
  `bridge_burst_flush_item`.
- Preserve Weixin image dispatch metadata only on the downstream dispatch event:
  `message_type`, `item_list`, `raw`, and `attachments`.

To refresh the tracked copies after changing the runtime plugin files:

```bash
cp /home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/monitor/monitor.ts \
  vendor/openclaw-weixin/src/monitor/monitor.ts
mkdir -p vendor/openclaw-weixin/src/messaging
cp /home/admin/.openclaw/plugins/openclaw-weixin-local/node_modules/@tencent-weixin/openclaw-weixin/src/messaging/process-message.ts \
  vendor/openclaw-weixin/src/messaging/process-message.ts
```

To inspect runtime logs:

```bash
journalctl -u openclaw-gateway.service -n 300 --no-pager | grep -Ei 'bridge_burst|flush_item|sort_fields'
grep -Ei 'bridge_burst|flush_item|sort_fields' /tmp/openclaw/openclaw-2026-05-01.log | tail -100
```
