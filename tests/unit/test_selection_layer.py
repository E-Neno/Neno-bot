"""理解+选择层：决策解析鲁棒性 + 兜底（绝不因它而不回）+ 异步调用。"""
from unittest.mock import patch

import pytest

from app.services.chat.selection_layer import (
    SelectionDecision, fallback_decision, parse_decision,
    build_selection_prompt, build_selection_guidance, select_response, select_response_sync,
)

_BATCH = [
    {"id": 11, "content": "在吗"},
    {"id": 12, "content": "我今天被裁了"},
    {"id": 13, "content": "在不在"},
]


def test_fallback_is_respond_everything():
    d = fallback_decision(_BATCH)
    assert d.focus == [11, 12, 13]
    assert d.ignore == [] and d.hooked_by is None
    assert d.reply_strategy == "merge" and d.should_respond is True
    assert d.depth == "shallow"


def test_parse_valid_decision():
    raw = '{"focus":[12],"ignore":[11,13],"hooked_by":12,"reply_strategy":"single","should_respond":true,"depth":"deep","emotion":{"hit":true,"tone":"心里一沉","intensity":0.8}}'
    d = parse_decision(raw, _BATCH)
    assert d.focus == [12] and d.ignore == [11, 13]
    assert d.hooked_by == 12 and d.reply_strategy == "single" and d.should_respond is True
    assert d.depth == "deep"
    assert d.emotion_hit is True and d.emotion_tone == "心里一沉"
    assert d.emotion_intensity == 0.8


def test_parse_invalid_depth_and_emotion_use_safe_defaults():
    raw = '{"focus":[12],"ignore":[],"hooked_by":null,"reply_strategy":"single","should_respond":true,"depth":"essay","emotion":{"hit":"yes","tone":123,"intensity":9}}'
    d = parse_decision(raw, _BATCH)
    assert d.depth == "shallow"
    assert d.emotion_hit is False
    assert d.emotion_tone == ""
    assert d.emotion_intensity == 1.0


def test_parse_filters_hallucinated_ids():
    # LLM 编了不属于这波的 id 99 → 必须被过滤掉
    raw = '{"focus":[99,12],"ignore":[88],"hooked_by":77,"reply_strategy":"merge","should_respond":true}'
    d = parse_decision(raw, _BATCH)
    assert 99 not in d.focus and d.focus == [12]
    assert d.ignore == []          # 88 不合法被滤
    assert d.hooked_by is None     # 77 不合法 → None


def test_parse_bad_strategy_defaults_merge():
    raw = '{"focus":[12],"ignore":[],"hooked_by":null,"reply_strategy":"yell","should_respond":true}'
    assert parse_decision(raw, _BATCH).reply_strategy == "merge"


def test_parse_missing_should_respond_defaults_true():
    raw = '{"focus":[12],"ignore":[],"hooked_by":null,"reply_strategy":"single"}'
    assert parse_decision(raw, _BATCH).should_respond is True


def test_parse_non_json_falls_back():
    d = parse_decision("我觉得应该回第二条", _BATCH)
    assert d.focus == [11, 12, 13] and d.should_respond is True  # = fallback


def test_parse_hooked_by_forced_into_focus():
    raw = '{"focus":[11],"ignore":[],"hooked_by":12,"reply_strategy":"single","should_respond":true}'
    d = parse_decision(raw, _BATCH)
    assert 12 in d.focus


def test_parse_respond_true_but_empty_focus_backfills():
    raw = '{"focus":[],"ignore":[11],"hooked_by":null,"reply_strategy":"merge","should_respond":true}'
    d = parse_decision(raw, _BATCH)
    assert d.focus == [12, 13]   # 要回却没挑 → 兜底聚焦没被忽略的


def test_parse_can_choose_not_to_respond():
    raw = '{"focus":[],"ignore":[11,12,13],"hooked_by":null,"reply_strategy":"single","should_respond":false}'
    d = parse_decision(raw, _BATCH)
    assert d.should_respond is False  # 她可以选择这次不回


def test_parse_json_with_fence_and_noise():
    raw = '这是我的决定：\n```json\n{"focus":[12],"ignore":[],"hooked_by":null,"reply_strategy":"single","should_respond":true}\n```'
    assert parse_decision(raw, _BATCH).focus == [12]


def test_build_prompt_sections_state_and_messages():
    p = build_selection_prompt(_BATCH, {"mood": "有点烦", "relationship": "刚熟起来"})
    assert "内部状态" in p and "有点烦" in p and "刚熟起来" in p
    assert "一波消息" in p and "[12]" in p and "我今天被裁了" in p
    assert "depth" in p and "shallow" in p and "deep" in p


def test_build_guidance_reflects_decision():
    d = SelectionDecision(focus=[12], ignore=[11, 13], hooked_by=12,
                          reply_strategy="single", should_respond=True)
    g = build_selection_guidance(d, _BATCH)
    assert "重点回应" in g and "被裁" in g      # focus 那条进来
    assert "略过" in g and "在吗" in g          # ignore 那条标出来
    assert "勾住" in g                          # hooked
    assert "只挑一条" in g                       # single 策略


def test_build_guidance_split_disabled_degrades_to_single():
    # 默认关：split 决策不应给「拆成几条」的指令，降级成 single（防伪多条）。
    d = SelectionDecision(focus=[12], ignore=[], hooked_by=None,
                          reply_strategy="split", should_respond=True)
    with patch("app.services.chat.selection_layer.config.REPLY_SPLIT_ENABLED", False):
        g = build_selection_guidance(d, _BATCH)
    assert "拆成" not in g and "只挑一条" in g


def test_build_guidance_split_enabled_keeps_split():
    # 一键回退：开关打开时 split 仍给原指令。
    d = SelectionDecision(focus=[12], ignore=[], hooked_by=None,
                          reply_strategy="split", should_respond=True)
    with patch("app.services.chat.selection_layer.config.REPLY_SPLIT_ENABLED", True):
        g = build_selection_guidance(d, _BATCH)
    assert "拆成" in g


def test_select_response_sync_parses():
    raw = '{"focus":[12],"ignore":[11,13],"hooked_by":12,"reply_strategy":"single","should_respond":true}'
    d = select_response_sync(_BATCH, {"mood": "平静"}, model_name="m", api_key="k", url="u",
                             llm_client=lambda **kw: raw)
    assert d.focus == [12] and d.hooked_by == 12


@pytest.mark.asyncio
async def test_select_response_parses_mocked_llm():
    raw = '{"focus":[12],"ignore":[11,13],"hooked_by":12,"reply_strategy":"single","should_respond":true}'
    d = await select_response(
        _BATCH, {"mood": "平静"},
        model_name="deepseek/deepseek-chat", api_key="k", url="u",
        llm_client=lambda **kw: raw,
    )
    assert d.focus == [12] and d.hooked_by == 12


@pytest.mark.asyncio
async def test_select_response_no_key_falls_back():
    d = await select_response(
        _BATCH, {}, model_name="m", api_key=None, url="u",
        llm_client=lambda **kw: "should not be called",
    )
    assert d == fallback_decision(_BATCH)


@pytest.mark.asyncio
async def test_select_response_llm_error_falls_back():
    def _boom(**kw):
        raise RuntimeError("network down")
    with patch("app.services.chat.selection_layer.log_event"):
        d = await select_response(
            _BATCH, {}, model_name="m", api_key="k", url="u", llm_client=_boom,
        )
    assert d == fallback_decision(_BATCH)


@pytest.mark.asyncio
async def test_select_response_forwards_extra_body():
    # 厂商参数（MiMo 关深度思考）必须透传到 LLM 客户端
    captured = {}

    def _client(**kw):
        captured.update(kw)
        return '{"focus":[12],"ignore":[],"hooked_by":null,"reply_strategy":"single","should_respond":true}'

    await select_response(
        _BATCH, {}, model_name="mimo-v2.5-pro", api_key="k", url="u",
        extra_body={"thinking": {"type": "disabled"}}, llm_client=_client,
    )
    assert captured.get("extra_body") == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_select_response_empty_batch_falls_back():
    d = await select_response([], {}, model_name="m", api_key="k", url="u")
    assert d.focus == [] and d.should_respond is True
