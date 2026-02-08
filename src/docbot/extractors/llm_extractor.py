"""LLM-based fallback extractor for unsupported languages.

Sends source code + a structured extraction prompt to the LLM and parses
the JSON response into a FileExtraction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models import (
    Citation,
    EnvVar,
    FileExtraction,
    PublicSymbol,
    RaisedError,
)

logger = logging.getLogger(__name__)

# Max source chars to send to the LLM per file.
_MAX_SOURCE_CHARS = 8000

_EXTRACT_SYSTEM = """\
You are a code analysis assistant. Extract structured information from the \
source file provided. Return ONLY valid JSON — no markdown fences, no \
commentary."""

_EXTRACT_PROMPT = """\
Analyze this {language} source file and extract structured information.

File: {rel_path}

```
{source}
```

Return a JSON object with these keys:
- "symbols": array of {{"name": str, "kind": "function"|"class", "signature": str, "line": int}}
- "imports": array of module/package name strings
- "env_vars": array of {{"name": str, "line": int}}
- "errors": array of {{"expression": str, "line": int}}

Only include public symbols (not prefixed with _ or private). \
If uncertain, include it. Return ONLY the JSON object."""


class LLMExtractor:
    """Fallback extractor that uses an LLM to extract file structure.

    Because extraction happens in a synchronous ``extract_file()`` call
    (run inside ``asyncio.to_thread``), we spin up a temporary event loop
    when no running loop is available.
    """

    def __init__(self, llm_client: object) -> None:
        from ..llm import LLMClient

        assert isinstance(llm_client, LLMClient)
        self._client: LLMClient = llm_client

    def extract_file(
        self, abs_path: Path, rel_path: str, language: str
    ) -> FileExtraction:
        source = abs_path.read_text(encoding="utf-8", errors="replace")

        if len(source) > _MAX_SOURCE_CHARS:
            source = source[:_MAX_SOURCE_CHARS] + "\n... (truncated)"

        prompt = _EXTRACT_PROMPT.format(
            language=language,
            rel_path=rel_path,
            source=source,
        )

        try:
            raw = self._client.ask_sync(prompt, system=_EXTRACT_SYSTEM)
        except Exception as exc:
            logger.warning("LLM extraction failed for %s: %s", rel_path, exc)
            return FileExtraction()

        return self._parse_response(raw, rel_path)

    @staticmethod
    def _parse_response(raw: str, rel_path: str) -> FileExtraction:
        """Parse the LLM JSON response into a FileExtraction."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON for %s", rel_path)
            return FileExtraction()

        symbols: list[PublicSymbol] = []
        imports: list[str] = []
        env_vars: list[EnvVar] = []
        raised_errors: list[RaisedError] = []
        citations: list[Citation] = []

        for s in data.get("symbols", []):
            line = s.get("line", 0)
            name = s.get("name", "")
            if not name:
                continue
            cit = Citation(file=rel_path, line_start=line, line_end=line, symbol=name)
            symbols.append(PublicSymbol(
                name=name,
                kind=s.get("kind", "function"),
                signature=s.get("signature", name),
                citation=cit,
            ))
            citations.append(cit)

        for imp in data.get("imports", []):
            if isinstance(imp, str) and imp:
                imports.append(imp)

        for ev in data.get("env_vars", []):
            name = ev.get("name", "")
            if not name:
                continue
            line = ev.get("line", 0)
            env_vars.append(EnvVar(
                name=name,
                citation=Citation(file=rel_path, line_start=line, line_end=line),
            ))

        for err in data.get("errors", []):
            expr = err.get("expression", "")
            line = err.get("line", 0)
            raised_errors.append(RaisedError(
                expression=expr,
                citation=Citation(file=rel_path, line_start=line, line_end=line),
            ))

        return FileExtraction(
            symbols=symbols,
            imports=imports,
            env_vars=env_vars,
            raised_errors=raised_errors,
            citations=citations,
        )
