"""Legacy CLI module path compatibility shim.

This keeps older installed entrypoints (``docbot.app.cli:app``) working
while delegating all behavior to the unified modern CLI implementation.
"""

from __future__ import annotations

from ..cli import app

__all__ = ["app"]

