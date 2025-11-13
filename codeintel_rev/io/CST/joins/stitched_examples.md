# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `write_parquet`
   - span: start [125, 15] end [125, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

2. `uses_builder.py` — **Name** `polars`
   - span: start [124, 17] end [124, 23]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame = polars.DataFrame(records)

3. `uses_builder.py` — **Attribute** `write_parquet`
   - span: start [125, 4] end [125, 28]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsDataFrame#write_parquet().`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

4. `uses_builder.py` — **Name** `gate_import`
   - span: start [121, 38] end [121, 49]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/gate_import().`
   - evidence: module-path, qname
   - preview: polars = cast("PolarsModule", gate_import("polars", "use graph export"))

5. `uses_builder.py` — **Name** `data_frame`
   - span: start [125, 4] end [125, 14]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: data_frame.write_parquet(str(target))

6. `uses_builder.py` — **Call** `lower`
   - span: start [99, 21] end [99, 33]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#lower().`
   - evidence: module-path, span, name
   - preview: normalized = role.lower()

7. `uses_builder.py` — **Attribute** `DataFrame`
   - span: start [124, 17] end [124, 33]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/PolarsModule#DataFrame().`
   - evidence: module-path, span, name
   - preview: data_frame = polars.DataFrame(records)

8. `uses_builder.py` — **Name** `True`
   - span: start [126, 11] end [126, 15]
   - symbol: `local 18`
   - evidence: module-path, span
   - preview: return True

9. `uses_builder.py` — **Name** `str`
   - span: start [125, 29] end [125, 32]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, span, name
   - preview: data_frame.write_parquet(str(target))

10. `uses_builder.py` — **Name** `False`
   - span: start [123, 15] end [123, 20]
   - symbol: `scip-python python python-stdlib 3.11 builtins/ImportError#`
   - evidence: module-path, span
   - preview: return False
