# OpenSpec Change Proposal: CodeIntel Metrics and Measures Harmonization

## Quick Links

- **Proposal**: [proposal.md](./proposal.md) - Why this change and what it does
- **Design**: [design.md](./design.md) - Detailed technical design and architecture
- **Tasks**: [tasks.md](./tasks.md) - Step-by-step implementation checklist  
- **Spec**: [specs/codeintel-observability/spec.md](./specs/codeintel-observability/spec.md) - Requirements and acceptance scenarios
- **Implementation**: [implementation/](./implementation/) - All code and implementation guide

## For First-Time Readers

Start here if you're new to this change:

1. **Read [proposal.md](./proposal.md)** - High-level summary of the problem and solution
2. **Review [design.md](./design.md)** - Deep dive into architecture decisions and trade-offs
3. **Check [tasks.md](./tasks.md)** - Implementation roadmap with 4 phases

## For Implementers

Follow this sequence:

1. **Setup**: Run `scripts/bootstrap.sh` to prepare environment
2. **Plan**: Read [tasks.md](./tasks.md) - 4 phases with granular steps
3. **Code**: Use [implementation/](./implementation/) as reference
4. **Test**: Each phase has unit tests - run them before moving to next phase
5. **Validate**: Run `openspec validate codeintel-metrics-harmonization --strict`

## Key Changes Summary

### What's Being Added

- **Unified observability helper** - `codeintel_rev/mcp_server/common/observability.py` centralizing metrics timing
- **Standardized error handling** - Consistent RFC 9457 Problem Details across all adapters
- **Resource cleanup documentation** - Best practices for HTTP client lifecycle management
- **Holistic metrics integration** - Seamless integration with `kgfoundry_common.observability` infrastructure

### What's Being Changed

- **All 4 adapters** - Remove duplicated `_NoopObservation` and `_observe` boilerplate
- **Error response formatting** - Unified error envelope schema across adapters
- **VLLMClient lifecycle** - Documented cleanup in lifespan shutdown (already implemented)

### What's Being Removed

- **Duplicated metrics boilerplate** - `_NoopObservation` classes in text_search.py and semantic.py
- **Per-adapter observation helpers** - Local `_observe` context managers replaced by shared helper
- **Inconsistent error shapes** - Different error formats unified into standard Problem Details

## Design Principles Enforced

✅ **Zero Code Duplication** - Metrics helpers centralized in common module  
✅ **Holistic Integration** - Leverages existing `kgfoundry_common.observability` infrastructure  
✅ **Resource Cleanup** - Documented best practices for HTTP client lifecycle  
✅ **RFC 9457 Compliance** - All errors use Problem Details format  
✅ **100% AGENTS.MD Compliance** - Zero suppressions, best-in-class quality  
✅ **Structural Solutions** - No shortcuts or error suppression  

## Success Criteria

This change is complete when:

- ✅ Zero duplicated `_NoopObservation` classes across codebase
- ✅ Single shared `observe_duration` helper in common module
- ✅ All adapters use standardized observability pattern
- ✅ Consistent error envelope schema across all adapters
- ✅ Resource cleanup documented in architecture docs
- ✅ All tests pass (unit + integration)
- ✅ Zero Ruff/pyright/pyrefly errors
- ✅ 95%+ test coverage on new code
- ✅ Documentation complete and junior-developer friendly
- ✅ `openspec validate codeintel-metrics-harmonization --strict` passes

## Implementation Timeline

| Phase | Duration | Risk | Can Rollback? |
|-------|----------|------|---------------|
| Phase 1: Common Observability Module | 1 day | Low | Yes (no existing code touched) |
| Phase 2: Adapter Refactoring | 2 days | Low | Yes (per-adapter rollback) |
| Phase 3: Error Harmonization | 1 day | Low | Yes (incremental updates) |
| Phase 4: Documentation & Validation | 1 day | Low | N/A |
| **Total** | **5 days** | **Low** | **Yes (incremental)** |

## Getting Help

### For Concept Questions

- Read [proposal.md](./proposal.md) - Explains the problem and high-level solution
- Read [design.md](./design.md) - Section "Decisions" explains why each choice was made
- Check "Relationship to Existing Infrastructure" in design.md

### For Implementation Questions

- Check [tasks.md](./tasks.md) - Step-by-step instructions for each task
- Read code comments in [implementation/](./implementation/)
- Run tests to verify understanding: `pytest tests/codeintel_rev/test_observability.py -v`

### For Testing Questions

- Each phase in [tasks.md](./tasks.md) has verification steps
- See "Testing Strategy" section in design.md
- Use `pytest --cov` to check coverage

## Related Documents

- **AGENTS.MD** - Overall design principles and quality standards
- **openspec/AGENTS.md** - How to create and validate openspec proposals
- **codeintel_rev/CodeIntel MCP: Design Review and Improve.md** - Original design review (Section 5)
- **codeintel_rev/ErrorhandlingDraftimplementationplan** - Initial implementation draft
- **codeintel_rev/MetricsDetailedPRs.md** - Detailed PR breakdown (reference)

## Validation Commands

```bash
# Validate this proposal
openspec validate codeintel-metrics-harmonization --strict

# Run all quality gates (when implementing)
uv run ruff format && uv run ruff check --fix
uv run pyright --warnings --pythonversion=3.13
uv run pyrefly check
SKIP_GPU_WARMUP=1 uv run pytest tests/codeintel_rev/ -v --cov=codeintel_rev
make artifacts && git diff --exit-code

# Verify no new suppressions
python tools/check_new_suppressions.py codeintel_rev/

# Check architectural boundaries
python tools/check_imports.py
```

## Status

**Stage**: Proposed (awaiting review and approval)  
**Created**: 2025-11-08  
**Change ID**: `codeintel-metrics-harmonization`  
**Branch**: `openspec/codeintel-metrics-harmonization` (when implementing)  

## Next Steps

1. **Review**: Reviewers assess proposal, design, and tasks
2. **Approve**: Once approved, implementer begins Phase 1
3. **Implement**: Follow tasks.md sequentially, checking off items
4. **Validate**: Run all quality gates at end of each phase
5. **Archive**: Move to `openspec/changes/archive/` when complete

---

**Remember**: This is a holistic quality improvement with zero external API changes. Clients won't notice any difference - all changes are internal improvements to code quality, maintainability, and observability infrastructure alignment.

