import pytest

from stateguard.guard.parser import parse_guard_output


def test_guard_parser_contract():
    assert parse_guard_output({"judgement": "unknown", "progress_updates": [],
                               "verification_target": "reopen", "reason": "ambiguous"}).judgement == "unknown"
    with pytest.raises(ValueError):
        parse_guard_output({"judgement": "contradicted", "progress_updates": []})


def test_guard_parser_normalizes_common_judgement_aliases():
    assert parse_guard_output({"judgement": "correct"}).judgement == "verified"
    assert parse_guard_output({"judgement": "uncertain"}).judgement == "unknown"


@pytest.mark.parametrize("raw,expected", [
    ("scroll", "navigate_to_observable_state"),
    ("wait", "navigate_to_observable_state"),
    ("Copying the URL via Ctrl+C for inspection", "external_state_query"),
    ("Inspect a screenshot", "acquire_visual_evidence"),
])
def test_guard_parser_normalizes_free_text_evidence_strategies(raw, expected):
    result = parse_guard_output({
        "judgement": "unknown",
        "evidence_gap": {
            "missing_evidence": "visible confirmation",
            "attempted_strategy": raw,
            "recommended_strategy": raw,
        },
    })
    assert result.evidence_gap["missing_evidence"] == ["visible confirmation"]
    assert result.evidence_gap["recommended_strategy"] == expected
    assert result.evidence_gap["raw_recommended_strategy"] == raw


def test_guard_parser_preserves_unmapped_strategy_as_diagnostic():
    result = parse_guard_output({
        "judgement": "unknown",
        "evidence_gap": {"recommended_strategy": "invent a new proof ritual"},
    })
    assert result.evidence_gap["recommended_strategy"] is None
    assert result.evidence_gap["raw_recommended_strategy"] == "invent a new proof ritual"
