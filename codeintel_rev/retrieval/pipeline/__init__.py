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
    CodeRankLLMAdapter,
    Doc,
    NoopReranker,
    Reranker,
    RerankResult,
)
from codeintel_rev.retrieval.pipeline.stage0 import (
    SemanticStage0Request,
    Stage0Metadata,
    Stage0Options,
    Stage0Result,
    execute_semantic_stage0,
    run_stage0,
)

__all__ = [
    "CodeRankLLMAdapter",
    "Doc",
    "LateInteraction",
    "LateInteractionResult",
    "NoopReranker",
    "RerankResult",
    "Reranker",
    "SemanticStage0Request",
    "Stage0Metadata",
    "Stage0Options",
    "Stage0Result",
    "StageDecision",
    "StageGateConfig",
    "XTRLateInteraction",
    "decide_secondary_stage",
    "execute_semantic_stage0",
    "run_stage0",
]
