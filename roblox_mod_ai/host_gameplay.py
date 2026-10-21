"""Dispatch registered, independently verifiable host-owned gameplay adapters.

No adapter may silently synthesize a success result: a renderer must match
actual authored action routes and world/source contracts or return None.
The small model handles only unmatched, truly game-specific mechanics.
"""
from __future__ import annotations

from .host_mining import render_host_mining
from .host_mining_exchange import render_host_mining_exchange
from .host_trading import render_host_trading
from .host_currency import render_host_currency
from .host_earned_currency import render_host_earned_currency
from .host_peer_trade import render_host_peer_trade
from .host_peer_barter import render_host_peer_barter
from .host_progress_dashboard import render_host_progress_dashboard
from .host_mode_lock import render_host_mode_lock
from .host_mode_world_action import render_host_mode_world_action
from .host_performance_mode import render_host_performance_mode
from .host_space_progression import render_host_space_progression
from .host_world_setup import render_host_world_setup
from .host_upgrade_purchase import render_host_upgrade_purchase
from .spec import RobloxModuleSpec, RobloxProposal

RENDERERS = (render_host_mining_exchange, render_host_mining,
             render_host_trading, render_host_currency,
             render_host_earned_currency,
             render_host_peer_trade, render_host_peer_barter,
             render_host_space_progression,
             render_host_world_setup, render_host_upgrade_purchase,
             render_host_progress_dashboard, render_host_mode_lock,
             render_host_mode_world_action, render_host_performance_mode)


def render_host_gameplay(module: RobloxModuleSpec, proposal: RobloxProposal) -> str | None:
    results = [(render.__name__, code) for render in RENDERERS
               if (code := render(module, proposal)) is not None]
    if len(results) > 1:
        owners = ", ".join(name for name, _ in results)
        raise ValueError(
            "HOST_ADAPTER_CONFLICT: " + module.name + " is claimed by " + owners
            + "; split the source-owned responsibilities or tighten eligibility"
        )
    return results[0][1] if results else None
