"""Dispatch registered, independently verifiable host-owned gameplay adapters.

No adapter may silently synthesize a success result: a renderer must match
actual authored action routes and world/source contracts or return None.
The small model handles only unmatched, truly game-specific mechanics.
"""
from __future__ import annotations

from .host_mining import render_host_mining
from .host_trading import render_host_trading
from .host_currency import render_host_currency
from .spec import RobloxModuleSpec, RobloxProposal

RENDERERS = (render_host_mining, render_host_trading, render_host_currency)


def render_host_gameplay(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    results = [code for render in RENDERERS
               if (code := render(module, proposal)) is not None]
    if len(results) > 1:
        raise ValueError("Multiple host adapters claim the same game mechanic: " + module.name)
    return results[0] if results else None
