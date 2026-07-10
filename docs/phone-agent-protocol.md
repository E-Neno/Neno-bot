# Phone Agent v0 协议

## 边界

- Android APK 是原生应用，不复用 Web 控制台。
- PC Web 控制台是高级驾驶舱，只负责下任务、观察、确认和回放。
- v0 不接入 Neno 主聊天链路，不调用 `/mobile/conversations/neno/messages`。
- v0 不接触内核触摸驱动；动作后端只预留 `kernel_touch` 名称。

## 连接

Android APK 主动连接：

```text
WS /mobile/agent/ws?device_id=<local-device-id>
```

PC Web 控制台连接：

```text
WS /agent/ws?device_id=<local-device-id>
```

开发期鉴权使用：

```http
Authorization: Bearer <AGENT_DEV_TOKEN>
```

## 状态

- `idle`：待命
- `observing`：只观察
- `executing`：执行中
- `paused`：暂停
- `awaiting_confirmation`：等待确认
- `stopped`：急停
- `failed`：失败

## 风险等级

- `read_only`：只读观察
- `low`：低风险动作
- `medium`：中风险系统动作
- `high`：发送、删除、安装、授权、系统写入

## 消息类型

### hello

```json
{
  "type": "hello",
  "device_id": "xiaomi-14-local",
  "client": "android-apk",
  "protocol": "phone-agent-v0"
}
```

### observation

```json
{
  "type": "observation",
  "device_id": "xiaomi-14-local",
  "state": "idle",
  "foreground_app": "浏览器",
  "screen": {"width": 1080, "height": 2400},
  "capabilities": {
    "accessibility": true,
    "screenshot": true,
    "notification": false,
    "root_daemon": false,
    "kernel_touch": false
  }
}
```

### action_request

```json
{
  "type": "action_request",
  "action_id": "act_001",
  "tool": "tap",
  "risk": "low",
  "args": {"x": 5400, "y": 8200, "coordinate": "normalized_10000"},
  "reason": "点击搜索框"
}
```

### confirmation_request

```json
{
  "type": "confirmation_request",
  "action_id": "act_009",
  "risk": "high",
  "summary": "即将点击发送按钮",
  "reason": "用户要求回复当前聊天",
  "choices": ["allow_once", "deny", "stop"]
}
```

### action_result

```json
{
  "type": "action_result",
  "action_id": "act_001",
  "ok": true,
  "state": "executing",
  "message": "点击完成"
}
```

### stop

```json
{
  "type": "stop",
  "reason": "用户急停"
}
```
