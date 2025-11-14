# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Call** `str`
   - span: start [129, 29] end [129, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Name** `write_parquet`
   - span: start [129, 15] end [129, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

3. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

4. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

5. `uses_builder.py` — **Name** `None`
   - span: start [126, 24] end [126, 28]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: if frame_factory is None:

6. `uses_builder.py` — **Name** `records`
   - span: start [128, 31] end [128, 38]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

7. `uses_builder.py` — **Name** `str`
   - span: start [129, 29] end [129, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

8. `uses_builder.py` — **Name** `data_frame`
   - span: start [128, 4] end [128, 14]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

9. `uses_builder.py` — **Name** `Path`
   - span: start [106, 58] end [106, 62]
   - symbol: `scip-python python python-stdlib 3.11 pathlib/Path#`
   - evidence: module-path, span, name
   - preview: def _write_parquet(records: list[dict[str, str]], target: Path) -> bool:

10. `uses_builder.py` — **Name** `ImportError`
   - span: start [123, 11] end [123, 22]
   - symbol: `scip-python python python-stdlib 3.11 builtins/ImportError#`
   - evidence: module-path, span, name
   - preview: except ImportError:
