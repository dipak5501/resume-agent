from pathlib import Path

import pytest

from app.services.hiring_agent import _parse_eval

FIXTURE = Path(__file__).parent / "fixtures" / "hiring_agent_output.txt"


def test_parse_eval_from_captured_output():
    r = _parse_eval(FIXTURE.read_text())
    # 5 + 22 + 25 + 10 + 2 (bonus) − 6 (deductions) = 58
    assert r.overall == 58
    assert r.categories == {
        "open_source": 5,
        "self_projects": 22,
        "production": 25,
        "technical_skills": 10,
    }
    assert "Add live demo URLs to projects" in r.advice


def test_parse_eval_caps_category_at_max():
    # a category score above its max must not inflate the total
    blob = (
        "===EVAL_JSON===\n"
        '{"scores": {"open_source": {"score": 99, "max": 35, "evidence": "x"}, '
        '"self_projects": {"score": 0, "max": 30, "evidence": "x"}, '
        '"production": {"score": 0, "max": 25, "evidence": "x"}, '
        '"technical_skills": {"score": 0, "max": 10, "evidence": "x"}}, '
        '"bonus_points": {"total": 0, "breakdown": ""}, '
        '"deductions": {"total": 0, "reasons": ""}, '
        '"key_strengths": ["a"], "areas_for_improvement": ["b"]}\n'
        "===END_EVAL_JSON===\n"
    )
    assert _parse_eval(blob).overall == 35  # capped, not 99


def test_parse_eval_missing_block_raises():
    with pytest.raises(RuntimeError):
        _parse_eval("no sentinel json here")
