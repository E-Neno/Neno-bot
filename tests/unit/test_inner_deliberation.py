from app.services.chat.inner_deliberation import (
    DELIBERATION_LENSES,
    deliberate_sync,
    parse_impulse,
)


def test_parse_impulse_clamps_pull_and_keeps_private_reaction():
    impulse = parse_impulse(
        '{"drive":"想靠近一点","reaction":"先别急着安慰，听完再说","pull":1.7}',
        lens="approach",
    )

    assert impulse is not None
    assert impulse.lens == "approach"
    assert impulse.drive == "想靠近一点"
    assert impulse.reaction == "先别急着安慰，听完再说"
    assert impulse.pull == 1.0


def test_deliberation_runs_three_independent_lenses_and_survives_one_failure():
    seen = []

    def fake_client(**kwargs):
        system = kwargs["messages"][0]["content"]
        lens = next(item for item in DELIBERATION_LENSES if item in system)
        seen.append(lens)
        if lens == "boundary":
            raise RuntimeError("one branch failed")
        return '{"drive":"有反应","reaction":"先留一点余地","pull":0.6}'

    result = deliberate_sync(
        messages=[{"id": 1, "content": "我今天被裁了"}],
        state={"state": "有点累", "relationship": "很熟"},
        model_name="mimo",
        api_key="key",
        url="https://example.test",
        llm_client=fake_client,
    )

    assert set(seen) == set(DELIBERATION_LENSES)
    assert {item.lens for item in result} == {"approach", "association"}


def test_deliberation_without_key_degrades_to_empty():
    result = deliberate_sync(
        messages=[{"id": 1, "content": "嗯"}],
        state={},
        model_name="mimo",
        api_key=None,
        url="https://example.test",
    )
    assert result == []
