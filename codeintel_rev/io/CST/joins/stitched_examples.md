# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Attribute** `write_parquet`
   - span: start [125, 4] end [125, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Name** `True`
   - span: start [126, 11] end [126, 15]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: return True

3. `uses_builder.py` — **Name** `list`
   - span: start [105, 28] end [105, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/list#`
   - evidence: module-path, span, name
   - preview: def _write_parquet(records: list[dict[str, str]], target: Path) -> bool:

4. `uses_builder.py` — **Name** `write_parquet`
   - span: start [125, 15] end [125, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

5. `uses_builder.py` — **Name** `ImportError`
   - span: start [122, 11] end [122, 22]
   - symbol: `scip-python python python-stdlib 3.11 builtins/ImportError#`
   - evidence: module-path, span, name
   - preview: except ImportError:

6. `uses_builder.py` — **Name** `data_frame`
   - span: start [125, 4] end [125, 14]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

7. `uses_builder.py` — **Name** `data_frame`
   - span: start [124, 4] end [124, 14]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame = polars.DataFrame(records)

8. `uses_builder.py` — **Name** `str`
   - span: start [125, 29] end [125, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

9. `uses_builder.py` — **Call** `str`
   - span: start [125, 29] end [125, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

10. `uses_builder.py` — **Name** `target`
   - span: start [125, 33] end [125, 39]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))
