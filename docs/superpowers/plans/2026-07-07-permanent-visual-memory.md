# 永久视觉记忆实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 Neno 增加永久图片资产库，并让当前轮回复模型直接接收图片 block，同时提供受控的历史图片回想工具。

**架构：** 聊天历史和 SQLite message 继续只保存文本投影与稳定 metadata；图片字节进入 `data/visual_assets` 并通过 `visual_assets`、`visual_asset_links`、`visual_observations` 追踪。当前轮图片在 `context_builder` 最后一条 user content 内追加 image block，旧图只通过 `visual_memory.search/inspect` 主动读取。

**技术栈：** Python、SQLite、Pydantic、OpenRouter chat messages 多模态 content block、pytest。

---

### 任务 1：视觉资产表与归档服务

**文件：**
- 修改：`app/storage/db.py`
- 修改：`app/schemas.py`
- 创建：`app/services/visual_asset_store.py`
- 测试：`tests/unit/test_visual_asset_store.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_archive_local_image_dedupes_by_sha256(tmp_path):
    # 初始化临时 DB，写入同一张 PNG 两次
    # 期望 asset_uid 相同、物理文件只需要一份、metadata 不含 base64
```

- [ ] **步骤 2：运行红灯**

运行：`python -m pytest tests/unit/test_visual_asset_store.py -q`
预期：FAIL，缺少 `app.services.visual_asset_store` 或视觉表。

- [ ] **步骤 3：实现最小代码**

新增 `visual_assets`、`visual_asset_links`、`visual_observations` 表；实现 `VisualAssetStore.archive_image_attachment()`，只接受本地 `media_path`，按 SHA-256 去重并复制到永久目录。

- [ ] **步骤 4：运行绿灯**

运行：`python -m pytest tests/unit/test_visual_asset_store.py -q`
预期：PASS。

### 任务 2：当前轮多模态 prompt

**文件：**
- 修改：`app/services/chat/context_builder.py`
- 修改：`app/services/chat/turn_orchestrator.py`
- 测试：`tests/unit/test_visual_chat_context.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_current_turn_images_are_appended_after_user_text():
    # build_chat_messages(..., current_turn_image_inputs=["data:image/png;base64,abc"])
    # 期望最后一条 user content 的最后一个 block 是 image_url
    # 历史 content 中没有 image_url
```

- [ ] **步骤 2：运行红灯**

运行：`python -m pytest tests/unit/test_visual_chat_context.py -q`
预期：FAIL，`build_chat_messages` 不支持图片输入。

- [ ] **步骤 3：实现最小代码**

给 `build_chat_messages()` 和 `load_chat_contexts()` 增加 `current_turn_image_inputs`，只把 image block 追加到最后 user message。

- [ ] **步骤 4：运行绿灯**

运行：`python -m pytest tests/unit/test_visual_chat_context.py -q`
预期：PASS。

### 任务 3：入口归档与 caption fallback 保留

**文件：**
- 修改：`app/config.py`
- 修改：`app/services/mobile_api_service.py`
- 修改：`app/routers/chat.py`
- 修改：`app/routers/platform.py`
- 测试：`tests/integration/test_mobile_api.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_mobile_image_visual_memory_archives_without_caption_normalization(...):
    # VISUAL_MEMORY_ENABLED=True
    # 发送本地 image attachment
    # 期望不调用 normalize_multimodal_message，run_chat_turn 收到文本投影和 visual_assets metadata
```

- [ ] **步骤 2：运行红灯**

运行：`python -m pytest tests/integration/test_mobile_api.py::test_mobile_image_visual_memory_archives_without_caption_normalization -q`
预期：FAIL，入口仍强制 caption normalization。

- [ ] **步骤 3：实现最小代码**

新增配置项；在视觉记忆开启且图片可归档时，生成 `[用户发送了一张图片]` 文本投影并写入 `input_record["visual_assets"]`。视觉记忆关闭或归档失败时沿用现有 caption 路线。

- [ ] **步骤 4：运行绿灯**

运行：`python -m pytest tests/integration/test_mobile_api.py::test_mobile_image_visual_memory_archives_without_caption_normalization -q`
预期：PASS。

### 任务 4：视觉回想 search/inspect

**文件：**
- 创建：`app/services/visual_recall_tool.py`
- 修改：`app/storage/db.py`
- 测试：`tests/unit/test_visual_recall_tool.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_visual_recall_search_finds_assets_by_message_text(tmp_path):
    # 插入图片消息和 link，query 命中文本投影
    # 期望返回 asset_uid、message_id、projection、mime_type
```

- [ ] **步骤 2：运行红灯**

运行：`python -m pytest tests/unit/test_visual_recall_tool.py -q`
预期：FAIL，缺少 recall tool。

- [ ] **步骤 3：实现最小代码**

实现 `search_visual_memory()` 与 `inspect_visual_asset()`；inspect 读取永久文件，调用现有多模态理解函数，并 append-only 写入 `visual_observations`。

- [ ] **步骤 4：运行绿灯**

运行：`python -m pytest tests/unit/test_visual_recall_tool.py -q`
预期：PASS。

### 任务 5：私有视觉回想循环与文档

**文件：**
- 修改：`app/services/chat/turn_orchestrator.py`
- 修改：`NENO.md`
- 修改：`NENO_ARCHITECTURE.md`
- 修改：`docs/wx-image-input-route-v1_1.md`
- 测试：`tests/unit/test_visual_recall_loop.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_visual_recall_tag_is_not_persisted_as_assistant_reply(...):
    # 第一次模型输出 <visual_recall>{...}</visual_recall>
    # 期望后端执行 inspect，再二次生成最终回复，落库的是最终回复
```

- [ ] **步骤 2：运行红灯**

运行：`python -m pytest tests/unit/test_visual_recall_loop.py -q`
预期：FAIL，当前会把工具标签当普通回复保存。

- [ ] **步骤 3：实现最小代码**

识别单个 `<visual_recall>` JSON 请求；执行 search/inspect；把 `【视觉回想】` 临时块插入 prompt 后二次生成。失败时插入降级文本，不写 `life_world_state`。

- [ ] **步骤 4：运行绿灯与回归**

运行：`python -m pytest tests/unit/test_visual_asset_store.py tests/unit/test_visual_chat_context.py tests/unit/test_visual_recall_tool.py tests/unit/test_visual_recall_loop.py tests/integration/test_mobile_api.py::test_mobile_send_message_normalizes_image_attachment -q`
预期：PASS。
