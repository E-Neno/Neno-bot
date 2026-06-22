"""自我库纯逻辑：归纳偏好结晶 + 防身份膨胀守门。"""
from app.services.consciousness.self_facts import (
    self_fact_tag, self_fact_content, guard_self_fact,
    learn_fact_tag, learn_fact_content,
)


def test_self_fact_tag_namespaced():
    assert self_fact_tag("reading") == "activity:reading"


def test_self_fact_content_is_hedged_preference():
    c = self_fact_content("画画")
    assert "画画" in c
    assert "像是" in c  # 对冲措辞——反复做是偏好，不是身份断言


def test_self_fact_content_second_person():
    # 喂回 self_context 用第二人称「你」
    assert "你" in self_fact_content("读书")


def test_guard_accepts_plain_preference():
    assert guard_self_fact("「画画」像是你常做、喜欢上手的事。") is True


def test_guard_rejects_biography_terms():
    # 反复做某事不许结晶成身份：专业/学校/家乡等一律拒
    assert guard_self_fact("「画画」说明你是设计专业的。") is False
    assert guard_self_fact("你常去学校画画。") is False


def test_guard_rejects_digits():
    assert guard_self_fact("你今天画了3次画。") is False


def test_learn_fact_tag_namespaced():
    assert learn_fact_tag("吉他") == "learn:吉他"


def test_learn_fact_content_is_learning_not_mastery():
    c = learn_fact_content("做提拉米苏")
    assert "做提拉米苏" in c
    assert "在学" in c  # 在学/上手，不是精通/科班
    assert "你" in c    # 第二人称，喂回 self_context


def test_learn_fact_content_passes_guard():
    assert guard_self_fact(learn_fact_content("吉他")) is True


def test_learn_fact_with_biography_topic_blocked_by_guard():
    # 即便主题混进身份词，守门也挡（学某事推不出身份/学历）
    assert guard_self_fact(learn_fact_content("在大学念的专业")) is False


def test_guard_reuses_self_context_term_list():
    # 防伪词汇必须和 self_context 同源，避免两套边界漂移
    from app.services.consciousness import self_context, self_facts
    assert self_facts.HIGH_RISK_BIOGRAPHY_TERMS is self_context.HIGH_RISK_BIOGRAPHY_TERMS
