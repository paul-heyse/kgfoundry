"""Overview of flows.

This module bundles flows logic for the kgfoundry stack. It groups related helpers so downstream
packages can import a single cohesive namespace. Refer to the functions and classes below for
implementation specifics.
"""

# [nav:section public-api]

from __future__ import annotations

from prefect import flow, task

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "e2e_flow",
    "t_echo",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


def _t_echo_impl(msg: str) -> str:
    """Echo a message string.

    Simple task implementation that returns the input message unchanged.
    Used for testing Prefect flow orchestration.

    Parameters
    ----------
    msg : str
        Message string to echo.

    Returns
    -------
    str
        The input message unchanged.
    """
    return msg


# [nav:anchor t_echo]
t_echo = task(_t_echo_impl)


def _e2e_flow_impl() -> list[str]:
    """Execute end-to-end pipeline skeleton flow.

    Runs a sequence of echo tasks representing the complete kgfoundry
    pipeline stages: harvest, doctags, chunk, embed_dense, encode_splade,
    bm25, faiss, ontology, concept_embed, linker, and kg.

    Returns
    -------
    list[str]
        List of task result strings.
    """
    return [
        t_echo.submit(x).result()
        for x in [
            "harvest",
            "doctags",
            "chunk",
            "embed_dense",
            "encode_splade",
            "bm25",
            "faiss",
            "ontology",
            "concept_embed",
            "linker",
            "kg",
        ]
    ]


# [nav:anchor e2e_flow]
e2e_flow = flow(name="kgfoundry_e2e_skeleton")(_e2e_flow_impl)
