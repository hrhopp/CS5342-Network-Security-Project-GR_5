"""Turn text into vectors with nomic-embed-text via the local Ollama server.

Documents and queries get different task prefixes (see config). Every vector
is checked for the expected dimension so a wrong model can't silently fill
the database with incomparable vectors.
"""
from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from src import config


@lru_cache(maxsize=1)
def _model() -> OllamaEmbeddings:
    return OllamaEmbeddings(model=config.EMBED_MODEL, base_url=config.OLLAMA_BASE_URL)


def _check_dims(vectors: list[list[float]]) -> list[list[float]]:
    for v in vectors:
        if len(v) != config.EMBED_DIM:
            raise ValueError(f"expected {config.EMBED_DIM}-dim vectors from "
                             f"{config.EMBED_MODEL}, got {len(v)}")
    return vectors


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Vectors for chunks being stored."""
    return _check_dims(_model().embed_documents(
        [config.EMBED_DOC_PREFIX + t for t in texts]))


def embed_query(text: str) -> list[float]:
    """Vector for a user question (Step 6)."""
    return _check_dims([_model().embed_query(config.EMBED_QUERY_PREFIX + text)])[0]
