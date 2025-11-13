# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

2. `uses_builder.py` — **Name** `None`
   - span: start [126, 24] end [126, 28]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: if frame_factory is None:

3. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

4. `uses_builder.py` — **Name** `resolve_polars_frame_factory`
   - span: start [125, 20] end [125, 48]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.polars_support`/resolve_polars_frame_factory().`
   - evidence: module-path, qname
   - preview: frame_factory = resolve_polars_frame_factory(polars)

5. `uses_builder.py` — **Name** `write_parquet`
   - span: start [129, 15] end [129, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

6. `uses_builder.py` — **Name** `records`
   - span: start [128, 31] end [128, 38]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

7. `uses_builder.py` — **Call** `gate_import`
   - span: start [122, 38] end [122, 79]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/gate_import().`
   - evidence: module-path, qname
   - preview: polars = cast("PolarsModule", gate_import("polars", "use graph export"))

8. `uses_builder.py` — **Name** `data_frame`
   - span: start [129, 4] end [129, 14]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

9. `uses_builder.py` — **Call** `str`
   - span: start [129, 29] end [129, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

10. `uses_builder.py` — **Name** `cast`
   - span: start [122, 17] end [122, 21]
   - symbol: `scip-python python python-stdlib 3.11 typing/cast().`
   - evidence: module-path, span, name
   - preview: polars = cast("PolarsModule", gate_import("polars", "use graph export"))
