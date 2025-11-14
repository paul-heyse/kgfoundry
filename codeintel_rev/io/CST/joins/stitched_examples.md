# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `write_parquet`
   - span: start [129, 15] end [129, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Name** `str`
   - span: start [129, 29] end [129, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

3. `uses_builder.py` — **Call** `str`
   - span: start [129, 29] end [129, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

4. `uses_builder.py` — **Name** `gate_import`
   - span: start [122, 38] end [122, 49]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/gate_import().`
   - evidence: module-path, qname
   - preview: polars = cast("PolarsModule", gate_import("polars", "use graph export"))

5. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

6. `uses_builder.py` — **Name** `frame_factory`
   - span: start [125, 4] end [125, 17]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: frame_factory = resolve_polars_frame_factory(polars)

7. `uses_builder.py` — **Name** `records`
   - span: start [128, 31] end [128, 38]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

8. `uses_builder.py` — **Name** `False`
   - span: start [127, 15] end [127, 20]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: return False

9. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

10. `uses_builder.py` — **Name** `polars`
   - span: start [125, 49] end [125, 55]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: frame_factory = resolve_polars_frame_factory(polars)
