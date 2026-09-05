"""Full parity gate against the real committed data (slow; needs a current DB).

Run: pytest -m slow          (after `python -m src.db rebuild` or an update run)
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not Path("data/turn.duckdb").exists(),
                    reason="no database — run `python -m src.db rebuild` first")
def test_db_matches_legacy_round_documents():
    from tools.parity import check
    assert check() == []
