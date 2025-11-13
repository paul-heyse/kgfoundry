# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `target`
   - span: start [125, 33] end [125, 39]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Name** `ImportError`
   - span: start [122, 11] end [122, 22]
   - symbol: `scip-python python python-stdlib 3.11 builtins/ImportError#`
   - evidence: module-path, span, name
   - preview: except ImportError:

3. `uses_builder.py` — **Name** `str`
   - span: start [85, 31] end [85, 34]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: def _is_definition(roles: list[str]) -> bool:

4. `uses_builder.py` — **Call** `write_parquet`
   - span: start [125, 4] end [125, 41]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

5. `uses_builder.py` — **Call** `str`
   - span: start [125, 29] end [125, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

6. `uses_builder.py` — **Name** `str`
   - span: start [125, 29] end [125, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

7. `uses_builder.py` — **Name** `records`
   - span: start [124, 34] end [124, 41]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame = polars.DataFrame(records)

8. `uses_builder.py` — **Name** `True`
   - span: start [126, 11] end [126, 15]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: return True

9. `uses_builder.py` — **Call** `DataFrame`
   - span: start [124, 17] end [124, 42]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsModule#DataFrame().`
   - evidence: module-path, span, name
   - preview: data_frame = polars.DataFrame(records)

10. `uses_builder.py` — **Name** `endswith`
   - span: start [100, 52] end [100, 60]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#endswith().`
   - evidence: module-path, span, name
   - preview: if "definition" in normalized or normalized.endswith("def"):
