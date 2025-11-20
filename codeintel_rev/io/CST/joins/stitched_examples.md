# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `uses_builder.py` — **Name** `role`
   - span: start [125, 21] end [125, 25]
   - symbol: `local 9`
   - evidence: module-path, span
   - preview: normalized = role.lower()

2. `uses_builder.py` — **Call** `lower`
   - span: start [125, 21] end [125, 33]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#lower().`
   - evidence: module-path, span, name
   - preview: normalized = role.lower()

3. `uses_builder.py` — **Name** `True`
   - span: start [127, 19] end [127, 23]
   - symbol: `local 10`
   - evidence: module-path, span
   - preview: return True

4. `uses_builder.py` — **Name** `jsonl_fallback`
   - span: start [106, 23] end [106, 37]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.uses_builder`/write_use_graph().(path)`
   - evidence: module-path, span
   - preview: jsonl_fallback=jsonl_fallback,

5. `uses_builder.py` — **Name** `_is_definition`
   - span: start [111, 4] end [111, 18]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.uses_builder`/_is_definition().`
   - evidence: module-path, span, name
   - preview: def _is_definition(roles: list[str]) -> bool:

6. `uses_builder.py` — **Attribute** `path`
   - span: start [71, 36] end [71, 44]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.enrich.scip_reader`/Document#path.`
   - evidence: module-path, span, name
   - preview: edges.append((def_path, doc.path, symbol))

7. `uses_builder.py` — **Name** `endswith`
   - span: start [126, 52] end [126, 60]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#endswith().`
   - evidence: module-path, span, name
   - preview: if "definition" in normalized or normalized.endswith("def"):

8. `uses_builder.py` — **Name** `normalized`
   - span: start [126, 41] end [126, 51]
   - symbol: `local 10`
   - evidence: module-path, span
   - preview: if "definition" in normalized or normalized.endswith("def"):

9. `uses_builder.py` — **Name** `normalized`
   - span: start [125, 8] end [125, 18]
   - symbol: `local 9`
   - evidence: module-path, span
   - preview: normalized = role.lower()

10. `uses_builder.py` — **Attribute** `endswith`
   - span: start [126, 41] end [126, 60]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#endswith().`
   - evidence: module-path, span, name
   - preview: if "definition" in normalized or normalized.endswith("def"):
