"""Regression tests for renderer LLM execution on a single event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path

from docbot.llm import LLMClient
from docbot.models import DocsIndex, ScopeResult
from docbot.pipeline.renderer import render_with_llm


def test_render_with_llm_uses_single_loop_for_llm_client(tmp_path: Path) -> None:
    index = DocsIndex(
        repo_path=str(tmp_path),
        generated_at="2026-02-08T00:00:00Z",
        languages=["python"],
        scopes=[
            ScopeResult(scope_id="a", title="A", paths=["a.py"], summary="scope a"),
            ScopeResult(scope_id="b", title="B", paths=["b.py"], summary="scope b"),
            ScopeResult(scope_id="c", title="C", paths=["c.py"], summary="scope c"),
        ],
    )

    llm = LLMClient(api_key="dummy", model="xiaomi/mimo-v2-flash", max_concurrency=1)
    llm._call_sync = lambda messages, json_mode=False: "generated markdown"

    written = asyncio.run(render_with_llm(index, tmp_path, llm))

    # All expected docs were produced successfully without cross-loop failures.
    assert len(written) >= 5
    assert (tmp_path / "README.generated.md").exists()
    assert (tmp_path / "docs" / "architecture.generated.md").exists()
    assert (tmp_path / "docs" / "modules" / "a.generated.md").exists()
