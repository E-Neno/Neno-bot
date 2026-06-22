"""自我库（刀① 阶段 3）：把落账的反复经历结晶成 subject="neno" 的归纳自我事实。

防伪边界（这一刀的命）：
- 自我事实只能从「正式 WorldLoop 落账、reflection 看得见」的经历来——这里只接 reflection 的
  活动 episode 统计，聊天写不进来。
- 做过 ≠ 身份：反复做某事只能结晶成**偏好/习惯**（对冲措辞「像是…」），
  **绝不**推断成专业/学校/家乡等身份/传记。守门器 `guard_self_fact` 硬挡身份词与数字。
- 当前自我可演变，经历历史不可逆——这里只产「偏好」候选，强化/淡化交给 salience，不否认旧事件。

纯逻辑（无 IO）；写库/去重/强化在 reflection_engine 里做。
"""
from __future__ import annotations

# 复用 self_context 的同一套高风险传记词表，保证防伪词汇统一。
from .self_context import HIGH_RISK_BIOGRAPHY_TERMS


def self_fact_tag(activity_key: str) -> str:
    """自我事实在 long_term_memory.tags 里的命名空间标签，用于去重/强化定位。"""
    return f"activity:{activity_key}"


def self_fact_content(label: str) -> str:
    """归纳偏好的对冲措辞（第二人称，喂回 self_context 用）。

    刻意用「像是…」而非断言：反复做 ≠ 身份，只是稳定偏好，且当前自我可演变。
    """
    return f"「{label}」像是你常做、喜欢上手的事。"


def learn_fact_tag(topic: str) -> str:
    """学习类自我事实在 tags 里的命名空间标签（按主题去重/强化）。"""
    return f"learn:{topic}"


def learn_fact_content(topic: str) -> str:
    """学习类直接事实的措辞（第二人称）。

    学习是「有持续身份意义的直接事实」——单次落账即可结晶（不必反复），
    但仍是「在学/上手」而非「精通/科班」，不推断成身份/学历。
    """
    return f"你最近在学着上手「{topic}」。"


def guard_self_fact(content: str) -> bool:
    """防身份膨胀硬守门：归纳偏好里出现任何身份/传记词或数字 → 拒绝结晶。

    与 self_context.guard_self_context 不同：那里允许「输入里已有」的身份词原样转述；
    这里是**结晶新事实**，反复做某事推不出身份，所以高风险词一律不许出现（无视来源）。
    """
    for term in HIGH_RISK_BIOGRAPHY_TERMS:
        if term in content:
            return False
    if any(char.isdigit() for char in content):
        return False
    return True
