# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `data_frame`
   - span: start [129, 4] end [129, 14]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Call** `frame_factory`
   - span: start [128, 17] end [128, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

3. `uses_builder.py` — **Name** `data_frame`
   - span: start [128, 4] end [128, 14]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

4. `uses_builder.py` — **Name** `records`
   - span: start [128, 31] end [128, 38]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

5. `uses_builder.py` — **Name** `polars`
   - span: start [122, 8] end [122, 14]
   - symbol: `local 17`
   - evidence: module-path, span
   - preview: polars = cast("PolarsModule", gate_import("polars", "use graph export"))

6. `uses_builder.py` — **Name** `str`
   - span: start [129, 29] end [129, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

7. `uses_builder.py` — **Call** `write_parquet`
   - span: start [129, 4] end [129, 41]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

8. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

9. `uses_builder.py` — **Name** `frame_factory`
   - span: start [126, 7] end [126, 20]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: if frame_factory is None:

10. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))
