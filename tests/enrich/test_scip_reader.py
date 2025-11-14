# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.enrich.scip_reader import SCIPIndex


def test_scip_reader_loads_documents(tmp_path: Path) -> None:
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
    assert index.documents
    document = index.by_file()["pkg/demo.py"]
    assert document.path == "pkg/demo.py"
    occurrences = document.occurrences
    assert occurrences and occurrences[0].symbol == "pkg.demo.func"
    symbol_map = index.symbol_to_files()
    assert symbol_map["pkg.demo.func"] == ["pkg/demo.py"]
    assert index.external_symbols["pkg.external.helper"].kind == "function"
