"""ChromaDB vector store: open the collection and ingest approved chunks.

Ingest flow:  integrity gate -> load -> chunk -> embed -> upsert into ChromaDB.
Chunk IDs are deterministic (Step 4), so re-running never creates duplicates,
and chunks already stored are skipped instead of re-embedded.

Usage (from the project root, venv active):
    python -m src.vectorstore --limit 32   # small test batch
    python -m src.vectorstore              # everything approved
    python -m src.vectorstore --stats      # what's stored
"""
import argparse
import sys
import time

# config must be imported BEFORE chromadb: it forces telemetry/tracing env
# flags off, which chromadb reads at import time.
from src import config
import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402

from src.chunker import IntegrityError, chunk_approved_files  # noqa: E402
from src.embeddings import embed_documents  # noqa: E402
from src.integrity import scan  # noqa: E402


def get_collection() -> chromadb.Collection:
    """Open (or create) the course collection. Shared entry point for teammates."""
    config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(config.CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False, allow_reset=False),
    )
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        configuration={"hnsw": {"space": config.DISTANCE_METRIC}},
        # None = never embed text by itself. Chroma's default would download
        # a different model from the internet and mix incompatible vectors in.
        embedding_function=None,
        metadata={"embed_model": config.EMBED_MODEL, "embed_dim": config.EMBED_DIM},
    )
    stored_model = (collection.metadata or {}).get("embed_model")
    if stored_model != config.EMBED_MODEL:
        raise RuntimeError(f"collection was built with {stored_model}, config says "
                           f"{config.EMBED_MODEL}; use a new COLLECTION_NAME and re-ingest")
    return collection


def ingest(limit: int | None = None) -> None:
    chunks = chunk_approved_files()          # raises IntegrityError if tampered
    if limit:
        chunks = chunks[:limit]
    collection = get_collection()
    if not chunks:
        print("No approved documents to ingest. Put PDFs in docs/raw/slides|textbook|quizzes/ "
              "and run python -m src.integrity first.")
        return

    # The DB mirrors the approved files currently in docs/raw: drop chunks of
    # older file versions (re-approved with --accept) and of removed files.
    # Skipped if no files are present, so an empty folder can't wipe the DB.
    present = sorted(set(scan().unchanged.values()))
    if present and collection.count():
        collection.delete(where={"sha256": {"$nin": present}})

    # Skip a chunk only if it is stored with IDENTICAL text. If the loader or
    # splitter changes (e.g. a text-cleaning fix), affected chunks get new text
    # under the same ID and are re-embedded automatically.
    current = {c.id: c for c in chunks}
    stored = collection.get(ids=list(current), include=["documents"])
    unchanged = {i for i, d in zip(stored["ids"], stored["documents"])
                 if d == current[i].page_content}
    todo = [c for c in chunks if c.id not in unchanged]

    # Chunks of present files that the pipeline no longer produces (e.g. a page
    # now splits into fewer chunks) would be stale leftovers: remove them.
    orphans = []
    if not limit and present:
        produced = set(current)
        orphans = [i for i in collection.get(where={"sha256": {"$in": present}},
                                             include=[])["ids"] if i not in produced]
        if orphans:
            collection.delete(ids=orphans)

    print(f"{len(chunks)} chunks approved: {len(unchanged)} already stored, "
          f"{len(todo)} new or changed to embed, {len(orphans)} stale removed")

    start = time.perf_counter()
    for i in range(0, len(todo), config.EMBED_BATCH_SIZE):
        batch = todo[i:i + config.EMBED_BATCH_SIZE]
        vectors = embed_documents([c.page_content for c in batch])
        collection.upsert(
            ids=[c.id for c in batch],
            embeddings=vectors,
            documents=[c.page_content for c in batch],
            metadatas=[c.metadata for c in batch],
        )
        done = i + len(batch)
        rate = done / (time.perf_counter() - start)
        eta = (len(todo) - done) / rate
        print(f"  {done}/{len(todo)} embedded | {rate:.1f} chunks/s | ETA {eta / 60:.1f} min",
              flush=True)

    print(f"Done. Collection '{config.COLLECTION_NAME}' now holds {collection.count()} chunks.")


def stats() -> None:
    collection = get_collection()
    print(f"Collection: {config.COLLECTION_NAME}  ({config.CHROMA_DIR})")
    print(f"Total chunks: {collection.count()}")
    for doc_type in sorted(set(config.DOC_TYPE_FOLDERS.values())):
        n = len(collection.get(where={"doc_type": doc_type}, include=[])["ids"])
        print(f"  {doc_type:<9} {n}")
    sample = collection.get(limit=1, include=["documents", "metadatas", "embeddings"])
    if sample["ids"]:
        print(f"\nSample id:  {sample['ids'][0]}")
        print(f"metadata:   {sample['metadatas'][0]}")
        print(f"vector:     {len(sample['embeddings'][0])} numbers, first 3 "
              f"{[round(float(x), 4) for x in sample['embeddings'][0][:3]]}")
        print(f"text:       {sample['documents'][0][:200]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Embed approved chunks into ChromaDB")
    parser.add_argument("--limit", type=int, help="only the first N chunks (test batch)")
    parser.add_argument("--stats", action="store_true", help="show what's stored")
    args = parser.parse_args()

    if args.stats:
        stats()
        return 0
    try:
        ingest(args.limit)
    except IntegrityError as e:
        print(f"REFUSED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
