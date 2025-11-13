# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Attribute** `write_parquet`
   - span: start [129, 4] end [129, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Call** `write_parquet`
   - span: start [129, 4] end [129, 41]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

3. `uses_builder.py` — **Name** `target`
   - span: start [129, 33] end [129, 39]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

4. `uses_builder.py` — **Call** `str`
   - span: start [129, 29] end [129, 40]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

5. `uses_builder.py` — **Name** `True`
   - span: start [130, 11] end [130, 15]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: return True

6. `uses_builder.py` — **Name** `records`
   - span: start [128, 31] end [128, 38]
   - symbol: `local 19`
   - evidence: module-path, span
   - preview: data_frame = frame_factory(records)

7. `uses_builder.py` — **Name** `normalized`
   - span: start [100, 8] end [100, 18]
   - symbol: `local 15`
   - evidence: module-path, span
   - preview: normalized = role.lower()

8. `uses_builder.py` — **Name** `str`
   - span: start [129, 29] end [129, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

9. `uses_builder.py` — **Name** `False`
   - span: start [127, 15] end [127, 20]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: return False

10. `uses_builder.py` — **Call** `lower`
   - span: start [100, 21] end [100, 33]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#lower().`
   - evidence: module-path, span, name
   - preview: normalized = role.lower()
