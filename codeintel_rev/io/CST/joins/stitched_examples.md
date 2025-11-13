# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `write_parquet`
   - span: start [129, 15] end [129, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Name** `polars`
   - span: start [125, 49] end [125, 55]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: frame_factory = resolve_polars_frame_factory(polars)

3. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

4. `uses_builder.py` — **Attribute** `write_parquet`
   - span: start [129, 4] end [129, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

5. `uses_builder.py` — **Call** `str`
   - span: start [129, 29] end [129, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

6. `uses_builder.py` — **Name** `False`
   - span: start [127, 15] end [127, 20]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: return False

7. `uses_builder.py` — **Call** `endswith`
   - span: start [101, 41] end [101, 67]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#endswith().`
   - evidence: module-path, span, name
   - preview: if "definition" in normalized or normalized.endswith("def"):

8. `uses_builder.py` — **Name** `None`
   - span: start [126, 24] end [126, 28]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: if frame_factory is None:

9. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

10. `uses_builder.py` — **Call** `frame_factory`
   - span: start [128, 17] end [128, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)
