"""Find the course chunks closest in meaning to a question. No LLM involved.

The question is embedded with the same model as the chunks (query prefix),
ChromaDB returns the nearest vectors, and two calibrated thresholds decide
whether the question is in scope at all. Public interface for teammates:

    from rag.retriever import retrieve
    for chunk in retrieve("What is a SYN flood?", doc_type="slides"):
        print(chunk.citation, chunk.similarity, chunk.text)

Usage:
    python -m rag.retriever "What is a SYN flood?"
    python -m rag.retriever "What is a SYN flood?" --type slides --k 6
"""
import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rag import config
from rag.embeddings import embed_query
from rag.vectorstore import get_collection


@dataclass
class RetrievedChunk:
    id: str
    text: str
    source: str
    page: int
    doc_type: str
    sha256: str
    distance: float          # cosine distance: smaller = more similar

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance

    @property
    def citation(self) -> str:
        """Human-readable label, e.g. 'Lecture 4, slide 12'. Built only from metadata."""
        title = " ".join(Path(self.source).stem.replace("_slides", "").split())
        unit = "slide" if self.doc_type == "slides" else "p."
        return f"{title}, {unit} {self.page}"


@lru_cache(maxsize=1)
def _collection():
    return get_collection()


def _where(doc_type: str | Sequence[str] | None) -> dict | None:
    """ChromaDB metadata filter for one doc_type, several, or all (None)."""
    if doc_type is None:
        return None
    if isinstance(doc_type, str):
        return {"doc_type": doc_type}
    return {"doc_type": {"$in": list(doc_type)}}


def retrieve(question: str, k: int = config.TOP_K,
             doc_type: str | Sequence[str] | None = None) -> list[RetrievedChunk]:
    """Top-k relevant chunks, or [] if the question isn't covered by the course.

    doc_type: "slides", "textbook", "quiz", a list of them, or None for all.
    """
    question = question.strip()
    # No letters or digits (empty, punctuation, invisible characters such as a
    # byte-order mark): nothing to search for, and such near-empty vectors can
    # land deceptively close to random chunks.
    if not re.search(r"[A-Za-z0-9]", question):
        return []
    if _collection().count() == 0:
        print("[retriever] knowledge base is empty: run python -m rag.vectorstore",
              file=sys.stderr)
        return []
    result = _collection().query(
        query_embeddings=[embed_query(question)],
        n_results=k,
        where=_where(doc_type),
        include=["documents", "metadatas", "distances"],
    )
    chunks = [
        RetrievedChunk(id=i, text=t, distance=d, source=m["source"], page=m["page"],
                       doc_type=m["doc_type"], sha256=m["sha256"])
        for i, t, m, d in zip(result["ids"][0], result["documents"][0],
                              result["metadatas"][0], result["distances"][0])
    ]
    if not chunks or chunks[0].distance > config.RELEVANCE_GATE:
        return []
    return [c for c in chunks if c.distance <= config.MAX_DISTANCE]


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the course knowledge base")
    parser.add_argument("question")
    parser.add_argument("--k", type=int, default=config.TOP_K)
    parser.add_argument("--type", choices=sorted(set(config.DOC_TYPE_FOLDERS.values())))
    args = parser.parse_args()

    chunks = retrieve(args.question, args.k, args.type)
    if not chunks:
        print(f"No course material is close enough (best distance > {config.RELEVANCE_GATE}).")
        return 0
    for rank, c in enumerate(chunks, 1):
        print(f"\n#{rank}  distance {c.distance:.3f} (similarity {c.similarity:.3f})  [{c.citation}]")
        print("   " + c.text[:300].replace("\n", "\n   "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
