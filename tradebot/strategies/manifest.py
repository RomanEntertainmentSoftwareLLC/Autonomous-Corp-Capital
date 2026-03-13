"""Expose strategy marketplace manifests."""

from __future__ import annotations

from tradebot.strategies.registry import STRATEGY_REGISTRY
from tradebot.strategies.base import StrategyMetadata


def strategy_manifest() -> list[dict]:
    manifest = []
    for cls in STRATEGY_REGISTRY.values():
        meta: StrategyMetadata = getattr(cls, "metadata", None)
        if meta is None:
            continue
        manifest.append(
            {
                "name": meta.name,
                "version": meta.version,
                "author": meta.author,
                "description": meta.description,
                "category": meta.category,
                "risk_profile": meta.risk_profile,
                "parameters": list(meta.parameters),
            }
        )
    return manifest
