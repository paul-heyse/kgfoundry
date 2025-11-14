# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `records`
   - span: start [128, 31] end [128, 38]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

2. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

3. `uses_builder.py` — **Call** `cast`
   - span: start [122, 17] end [122, 80]
   - symbol: `scip-python python python-stdlib 3.11 typing/cast().`
   - evidence: module-path, span, name
   - preview: polars = cast("PolarsModule", gate_import("polars", "use graph export"))

4. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

5. `uses_builder.py` — **Call** `str`
   - span: start [129, 29] end [129, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

6. `uses_builder.py` — **Name** `polars`
   - span: start [125, 49] end [125, 55]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: frame_factory = resolve_polars_frame_factory(polars)

7. `uses_builder.py` — **Call** `frame_factory`
   - span: start [128, 17] end [128, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

8. `uses_builder.py` — **Name** `records`
   - span: start [106, 19] end [106, 26]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.uses_builder`/_write_parquet().`
   - evidence: module-path, span
   - preview: def _write_parquet(records: list[dict[str, str]], target: Path) -> bool:

9. `uses_builder.py` — **Name** `None`
   - span: start [126, 24] end [126, 28]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: if frame_factory is None:

10. `uses_builder.py` — **Name** `str`
   - span: start [129, 29] end [129, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))
