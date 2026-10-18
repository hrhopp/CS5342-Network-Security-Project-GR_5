"""Split page Documents into chunks that carry the agreed metadata contract.

Every chunk carries exactly:
    {"source": "Lecture04_DoS.pdf", "page": 12, "doc_type": "slides",
     "sha256": "<approved fingerprint of the file>"}
Chunks never cross a page boundary, so each chunk has exactly one page number
-- that page number becomes the citation.

Usage (from the project root, venv active):
    python -m rag.chunker             # chunk all approved files, show 5 random chunks
    python -m rag.chunker --sample 10
"""
import argparse
import random
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag import config
from rag.integrity import list_documents, load_manifest, rel_name, scan, sha256_file
from rag.loader import load_pdf


class IntegrityError(Exception):
    """A file's bytes don't match its approved fingerprint."""


def doc_type_for(path: Path) -> str:
    """Map docs/raw/<folder>/file.pdf to its doc_type; reject anything else."""
    parts = path.relative_to(config.RAW_DOCS_DIR).parts
    if len(parts) != 2 or parts[0] not in config.DOC_TYPE_FOLDERS:
        allowed = ", ".join(f"docs/raw/{f}/" for f in config.DOC_TYPE_FOLDERS)
        raise ValueError(f"{rel_name(path)}: put it in one of {allowed}")
    return config.DOC_TYPE_FOLDERS[parts[0]]


def make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def chunk_file(path: Path, approved_sha256: str) -> list[Document]:
    """Load, split and label one file. Refuses if the file isn't the approved version."""
    doc_type = doc_type_for(path)
    pages, _ = load_pdf(path)

    # Re-hash AFTER reading: closes the window where the file could be swapped
    # between the integrity scan and the load.
    if sha256_file(path) != approved_sha256:
        raise IntegrityError(f"{rel_name(path)} changed since it was approved")

    splitter = make_splitter()
    chunks = []
    for page in pages:                       # split each page on its own
        for i, text in enumerate(splitter.split_text(page.page_content)):
            chunks.append(Document(
                # Deterministic ID: same file version + page + position -> same ID,
                # so re-ingesting overwrites instead of duplicating (Step 5).
                id=f"{approved_sha256[:16]}-p{page.metadata['page']}-c{i}",
                page_content=text,
                metadata={
                    "source": page.metadata["source"],
                    "page": page.metadata["page"],
                    "doc_type": doc_type,
                    "sha256": approved_sha256,
                },
            ))
    return chunks


def chunk_approved_files() -> list[Document]:
    """Chunk every file whose fingerprint is recorded and unchanged."""
    result = scan()
    if not result.ok:
        raise IntegrityError("modified files: " + ", ".join(result.changed)
                             + " -- run python -m rag.integrity")
    if result.new:
        print("Not yet approved (run python -m rag.integrity first): "
              + ", ".join(result.new))

    approved = load_manifest()["files"]
    chunks = []
    for path in list_documents():
        name = rel_name(path)
        if name in result.unchanged:
            chunks.extend(chunk_file(path, approved[name]["sha256"]))
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Chunk approved documents")
    parser.add_argument("--sample", type=int, default=5, help="random chunks to print")
    args = parser.parse_args()

    try:
        chunks = chunk_approved_files()
    except (IntegrityError, ValueError) as e:
        print(f"REFUSED: {e}")
        return 1

    sizes = [len(c.page_content) for c in chunks]
    print(f"{len(chunks)} chunks | size min {min(sizes, default=0)}, "
          f"max {max(sizes, default=0)}, avg {sum(sizes) // max(len(sizes), 1)} chars")

    for c in random.sample(chunks, min(args.sample, len(chunks))):
        print(f"\n{'=' * 70}\nid:       {c.id}\nmetadata: {c.metadata}\n{'-' * 70}")
        print(c.page_content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
