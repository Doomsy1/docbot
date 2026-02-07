"""Semantic search engine using BM25-lite algorithm.

Provides fast, local symbol search over extracted documentation.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import Citation, FileExtraction, PublicSymbol


@dataclass
class SearchResult:
    citation: Citation
    score: float
    match_context: str


class SearchIndex:
    """In-memory inverted index with BM25 ranking."""

    def __init__(self) -> None:
        self.documents: list[dict] = []  # Stores metadata for each indexed item
        self.inverted_index: dict[str, list[int]] = {}  # term -> list of doc_ids
        self.doc_lengths: list[int] = []  # Length of each doc in terms
        self.avg_doc_length: float = 0.0

    def add(self, file_path: str, extraction: FileExtraction) -> None:
        """Add symbols and content from a file extraction to the index."""
        # Index each symbol as a separate "document"
        for sym in extraction.symbols:
            text = f"{sym.name} {sym.kind} {sym.signature}"
            if sym.docstring_first_line:
                text += f" {sym.docstring_first_line}"
            
            self._index_item(
                text=text,
                citation=sym.citation,
                kind="symbol",
                name=sym.name
            )

        # Index the file itself as a document (path parts + basic terms)
        path_terms = file_path.replace("/", " ").replace(".", " ")
        self._index_item(
            text=f"{file_path} {path_terms}",
            citation=Citation(file=file_path, line_start=1, line_end=1, symbol=Path(file_path).name),
            kind="file",
            name=str(Path(file_path).name)
        )

    def _index_item(self, text: str, citation: Citation, kind: str, name: str) -> None:
        doc_id = len(self.documents)
        tokens = self._tokenize(text)
        doc_len = len(tokens)
        
        self.documents.append({
            "citation": citation,
            "kind": kind,
            "name": name,
            "text": text
        })
        self.doc_lengths.append(doc_len)

        for token in set(tokens):  # unique terms per doc for index mapping
            if token not in self.inverted_index:
                self.inverted_index[token] = []
            self.inverted_index[token].append(doc_id)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Search for query terms using BM25 ranking."""
        if not self.documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # BM25 Constants
        k1 = 1.5
        b = 0.75
        N = len(self.documents)
        self.avg_doc_length = sum(self.doc_lengths) / N if N > 0 else 0

        scores: dict[int, float] = {}

        for token in query_tokens:
            if token not in self.inverted_index:
                continue

            # IDF Calculation
            doc_list = self.inverted_index[token]
            df = len(doc_list)  # Document frequency
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)

            for doc_id in doc_list:
                # TF Calculation
                # We need term frequency in THIS document. 
                # Optimization: Could store Counter in self.documents, but re-tokenizing 
                # simplistic documents is fast enough for <10k symbols.
                term_count = self._tokenize(self.documents[doc_id]["text"]).count(token)
                
                doc_len = self.doc_lengths[doc_id]
                tf = (term_count * (k1 + 1)) / (term_count + k1 * (1 - b + b * (doc_len / self.avg_doc_length)))
                
                scores[doc_id] = scores.get(doc_id, 0.0) + (idf * tf)

        # Boost exact name matches
        for doc_id, score in scores.items():
            doc = self.documents[doc_id]
            if query.lower() == doc["name"].lower():
                scores[doc_id] = score * 2.0
            elif query.lower() in doc["name"].lower():
                scores[doc_id] = score * 1.5

        # Sort and format results
        results = []
        top_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        for doc_id, score in top_docs:
            doc = self.documents[doc_id]
            results.append(SearchResult(
                citation=doc["citation"],
                score=score,
                match_context=f"[{doc['kind']}] {doc['name']}"
            ))

        return results

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenizer: lowercase and split by non-alphanumeric."""
        # Keep it simple: split by whitespace, strip punctuation
        words = text.lower().split()
        clean = []
        for w in words:
            # Strip common punctuation
            w = w.strip(".,;:\"'()[]{}")
            if len(w) > 1:
                clean.append(w)
        return clean

    def save(self, path: Path) -> None:
        """Persist index to disk."""
        data = {
            "documents": [
                {
                    "citation": d["citation"].model_dump(),
                    "kind": d["kind"],
                    "name": d["name"],
                    "text": d["text"]
                }
                for d in self.documents
            ],
            "inverted_index": self.inverted_index,
            "doc_lengths": self.doc_lengths
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SearchIndex:
        """Load index from disk."""
        idx = cls()
        if not path.exists():
            return idx
            
        data = json.loads(path.read_text(encoding="utf-8"))
        
        idx.documents = []
        for d in data["documents"]:
            idx.documents.append({
                "citation": Citation(**d["citation"]),
                "kind": d["kind"],
                "name": d["name"],
                "text": d["text"]
            })
            
        idx.inverted_index = data["inverted_index"]
        idx.doc_lengths = data["doc_lengths"]
        return idx
