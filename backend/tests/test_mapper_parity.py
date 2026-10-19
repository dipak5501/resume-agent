"""Cross-language mapper parity (T18). One shared fixture set
(extension/tests/fixtures/mapper-parity.json) is fed to BOTH the backend
heuristic and the extension mapper (see extension/tests/mapper-parity.test.ts).
Both assert the same expected canonical, so if field_map.py and mapper.ts ever
drift, one side's test goes red. The extension is the canonical source of truth;
the backend mirrors it."""

import json
from pathlib import Path

import pytest

from app.schemas.autofill import FieldDescriptor
from app.services.field_map import heuristic_map

_FIXTURE = Path(__file__).parents[2] / "extension" / "tests" / "fixtures" / "mapper-parity.json"
_CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _CASES, ids=[c["note"] for c in _CASES])
def test_backend_matches_shared_fixture(case):
    r = heuristic_map(FieldDescriptor(**case["descriptor"]))
    canonical = r[0] if r else "unknown"  # backend None ≡ extension 'unknown'
    assert canonical == case["expected"], case["note"]
