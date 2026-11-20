"""Execution-location policy for NEXORA's production workload.

Production media processing, 3D generation and Godot exports must run on the
creator's paired local machine. The cloud API is a control plane and artifact
host only; it must fail closed if a client calls a local-compute endpoint.
"""
from __future__ import annotations

import re

_LOCAL_COMPUTE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^/api/projects/[^/]+/generate$",
        r"^/api/projects/[^/]+/godot-check$",
        r"^/api/projects/[^/]+/movie-pipeline/source/(?:photo|video)$",
        r"^/api/projects/[^/]+/movie-pipeline/stages/analysis/run$",
        r"^/api/projects/[^/]+/movie-pipeline/(?:player|environment|actors-props|audio|gameplay|assembly)/build$",
        r"^/api/v1/workspace/projects/[^/]+/video-intake$",
        r"^/api/v1/workspace/projects/[^/]+/assets$",
        r"^/api/v1/workspace/projects/[^/]+/assets/[^/]+/convert$",
        r"^/api/v1/workspace/projects/[^/]+/jobs$",
        r"^/api/v1/workspace/projects/[^/]+/creator-workflow/(?:pipeline|player/build|player/portrait|environment/build|actors-props/build|audio/build|gameplay/compile|assembly/build|video-check)$",
    )
)

_LOCAL_COMPUTE_METHODS = frozenset({"POST", "PUT", "PATCH"})


def is_local_compute_only_request(method: str, path: str) -> bool:
    """Return True for request paths that must never execute on cloud hosts."""
    if method.upper() not in _LOCAL_COMPUTE_METHODS:
        return False
    normalized_path = path.split("?", 1)[0]
    return any(pattern.fullmatch(normalized_path) for pattern in _LOCAL_COMPUTE_PATTERNS)


def local_compute_block_payload() -> dict:
    """Stable API error body for callers that accidentally target the cloud."""
    return {
        "detail": {
            "code": "LOCAL_COMPUTE_REQUIRED",
            "message": (
                "This production operation must run on the creator's paired "
                "NEXORA Local Compute Agent. The NEXORA cloud API does not "
                "process source media, generate 3D assets, or compile games."
            ),
            "next_step": "Connect and pass preflight on your NEXORA Local Compute Agent.",
        }
    }
