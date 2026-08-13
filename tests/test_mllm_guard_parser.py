import pytest

from stateguard.guard.parser import parse_guard_output


def test_guard_parser_contract():
    assert parse_guard_output({"judgement": "unknown", "progress_updates": [],
                               "verification_target": "reopen", "reason": "ambiguous"}).judgement == "unknown"
    with pytest.raises(ValueError):
        parse_guard_output({"judgement": "contradicted", "progress_updates": []})
