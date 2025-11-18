"""Composable retrieval pipeline helpers shared by MCP adapters."""

from codeintel_rev.retrieval.pipeline.gating import (
    StageDecision,
    StageGateConfig,
    decide_secondary_stage,
)
from codeintel_rev.retrieval.pipeline.late_interaction import (
    LateInteraction,
    LateInteractionResult,
    XTRLateInteraction,
)
from codeintel_rev.retrieval.pipeline.rerankers import (
    NoopReranker,
    Reranker,
    RerankResult,
)
from codeintel_rev.retrieval.pipeline.stage0 import (
    Stage0Options,
    Stage0Result,
    run_stage0,
)

__all__ = [
    "LateInteraction",
    "LateInteractionResult",
    "NoopReranker",
    "RerankResult",
    "Reranker",
    "Stage0Options",
    "Stage0Result",
    "StageDecision",
    "StageGateConfig",
    "XTRLateInteraction",
    "decide_secondary_stage",
    "run_stage0",
]
