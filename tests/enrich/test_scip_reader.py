# SPDX-License-Identifier: MIT
"""Tests for SCIP index reader and document loading."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.scip_reader import SCIPIndex

from tests._helpers import assertions


def test_scip_reader_loads_documents(tmp_path: Path) -> None:
    """Test that SCIPIndex loads documents, occurrences, and symbols correctly."""
    payload = {
        "documents": [
            {
                "relativePath": "pkg/demo.py",
                "occurrences": [
                    {"symbol": "pkg.demo.func", "range": [1, 0, 1, 4], "roles": ["definition"]}
                ],
                "symbols": [{"symbol": "pkg.demo.func", "kind": "function"}],
            }
        ],
        "externalSymbols": [{"symbol": "pkg.external.helper", "kind": "function"}],
    }
    scip_path = tmp_path / "index.scip.json"
    scip_path.write_text(json.dumps(payload), encoding="utf-8")

    index = SCIPIndex.load(scip_path)
    assertions.expect_true(bool(index.documents), reason="index should have documents")
    document = index.by_file()["pkg/demo.py"]
    assertions.expect_equal(document.path, "pkg/demo.py")
    occurrences = document.occurrences
    assertions.expect_true(bool(occurrences), reason="document should have occurrences")
    assertions.expect_equal(occurrences[0].symbol, "pkg.demo.func")
    symbol_map = index.symbol_to_files()
    assertions.expect_sequence_equal(symbol_map["pkg.demo.func"], ["pkg/demo.py"])
    assertions.expect_equal(index.external_symbols["pkg.external.helper"].kind, "function")
