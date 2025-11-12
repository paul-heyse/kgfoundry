# Stitched CST ⇄ SCIP examples

Sample joins to help with human QA of the stitching heuristics.

1. `typing.py` — **Name** `object`
   - span: start [139, 41] end [139, 47]
   - symbol: `scip-python python python-stdlib 3.11 builtins/object#`
   - evidence: module-path, name
   - preview: def randn(self, *shape: int, device: object | None = None) -> TorchTensor:

2. `typing.py` — **Name** `object`
   - span: start [251, 52] end [251, 58]
   - symbol: `scip-python python python-stdlib 3.11 builtins/object#`
   - evidence: module-path, name
   - preview: def DataFrame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame: # noqa: N802

3. `typing.py` — **Name** `str`
   - span: start [244, 49] end [244, 52]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, name
   - preview: def write_parquet(self, file: str | PathLike[str]) -> None: ...

4. `typing.py` — **Name** `object`
   - span: start [135, 35] end [135, 41]
   - symbol: `scip-python python python-stdlib 3.11 builtins/object#`
   - evidence: module-path, name
   - preview: def device(self, name: str) -> object:

5. `typing.py` — **Name** `HEAVY_DEPS`
   - span: start [43, 0] end [43, 10]
   - symbol: `scip-python python kgfoundry 0.1.0 `codeintel_rev.typing`/gate_import().(module_name)`
   - evidence: module-path, span
   - preview: HEAVY_DEPS = _BASE_HEAVY_DEPS

6. `typing.py` — **Name** `str`
   - span: start [251, 47] end [251, 50]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, name
   - preview: def DataFrame(self, data: Sequence[Mapping[str, object]]) -> PolarsDataFrame: # noqa: N802

7. `typing.py` — **Name** `str`
   - span: start [244, 34] end [244, 37]
   - symbol: `scip-python python python-stdlib 3.11 builtins/str#`
   - evidence: module-path, name
   - preview: def write_parquet(self, file: str | PathLike[str]) -> None: ...

8. `typing.py` — **Name** `NDArray`
   - span: start [24, 26] end [24, 33]
   - symbol: `local 4`
   - evidence: module-path, span
   - preview: type NDArrayAny = npt.NDArray[Any]

9. `typing.py` — **Name** `object`
   - span: start [192, 19] end [192, 25]
   - symbol: `scip-python python python-stdlib 3.11 builtins/object#`
   - evidence: module-path, name
   - preview: GpuIndexCagra: object | None

10. `typing.py` — **Name** `object`
   - span: start [52, 5] end [52, 11]
   - symbol: `scip-python python python-stdlib 3.11 builtins/object#`
   - evidence: module-path, name
   - preview: ) -> object:
