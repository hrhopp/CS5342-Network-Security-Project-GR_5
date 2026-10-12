"""Turn PDFs into page-level Documents, keeping track of each page's number.

One Document per PDF page, because the page number is what later becomes the
citation "(Lecture 4, slide 12)". Only our own metadata fields are kept: the
PDF's embedded metadata is attacker-controllable and is discarded.

Usage (from the project root, venv active):
    python -m src.loader                          # summary of every PDF
    python -m src.loader "Lecture 1_slides.pdf" 5 # print page 5 of one PDF
"""
import argparse
import re
import sys
import warnings
from pathlib import Path

from langchain_core.documents import Document

# langchain-community prints a "being sunset" DeprecationWarning on import.
# The package is pinned in requirements.txt and named in our report, so the
# warning is expected; silence only that one message.
warnings.filterwarnings("ignore", message=r".*langchain-community.*sunset",
                        category=DeprecationWarning)
from langchain_community.document_loaders import PyPDFLoader  # noqa: E402

from src import config  # noqa: E402
from src.integrity import list_documents, rel_name  # noqa: E402


# Some textbook fonts name characters instead of encoding them, so pypdf emits
# e.g. "/uni2295" where the page shows "⊕" (XOR). Turn the name back into the
# character it stands for (hex code point -> character). Variant glyphs carry a
# style suffix ("/uni2295.alt"), which is dropped.
GLYPH_NAME = re.compile(r"/uni([0-9A-Fa-f]{4})(?:\.(?:alt\w*|sc|ss\d+|case|sups|subs|lf|tf|osf))?")


def clean_text(text: str) -> str:
    """Decode glyph names, collapse runs of whitespace per line, drop blank lines."""
    text = GLYPH_NAME.sub(lambda m: chr(int(m.group(1), 16)), text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def load_pdf(path: Path) -> tuple[list[Document], list[int]]:
    """Load one PDF. Returns (kept pages, page numbers skipped as near-empty)."""
    raw_pages = PyPDFLoader(
        str(path), mode="page", extraction_mode=config.PDF_EXTRACTION_MODE
    ).load()

    pages, skipped = [], []
    for raw in raw_pages:
        page_no = raw.metadata["page"] + 1   # PyPDFLoader counts from 0; humans from 1
        text = clean_text(raw.page_content)
        if len(text) < config.MIN_PAGE_CHARS:
            skipped.append(page_no)
            continue
        # Allowlist: build fresh metadata instead of copying raw.metadata,
        # which carries the PDF's own (untrusted) author/producer/hidden fields.
        pages.append(Document(
            page_content=text,
            metadata={"source": path.name, "page": page_no},
        ))
    return pages, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect PDF text extraction")
    parser.add_argument("file", nargs="?", help="PDF name inside docs/raw")
    parser.add_argument("page", nargs="?", type=int, help="1-based page number to print")
    args = parser.parse_args()

    if args.file:
        path = config.RAW_DOCS_DIR / args.file
        if not path.is_file():
            print(f"No such file: {path}")
            return 1
        pages, skipped = load_pdf(path)
        if args.page:
            match = [p for p in pages if p.metadata["page"] == args.page]
            if not match:
                why = "skipped as near-empty" if args.page in skipped else "does not exist"
                print(f"Page {args.page} {why}.")
                return 1
            print(f"metadata: {match[0].metadata}\n{'-' * 60}")
            print(match[0].page_content)
            return 0
        targets = [path]
    else:
        targets = list_documents()

    total = 0
    for path in targets:
        pages, skipped = load_pdf(path)
        total += len(pages)
        print(f"{rel_name(path)}: {len(pages)} pages kept, skipped {skipped or 'none'}")
    print(f"\nTotal: {total} pages loaded from {len(targets)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
