"""SHA-256 integrity gate for the knowledge base.

Nothing enters the vector DB without a recorded fingerprint. Defends against
knowledge-base poisoning: if an already-approved document changes by even one
byte, ingestion is refused until a human reviews and re-approves it.

Usage (from the project root, venv active):
    python -m rag.integrity                      # check files, register new ones
    python -m rag.integrity --accept <file.pdf>  # re-approve a reviewed change
"""
import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from rag import config

MANIFEST_VERSION = 1


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of a file as 64 hex characters, read in blocks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(config.HASH_BLOCK_SIZE):
            h.update(block)
    return h.hexdigest()


def load_manifest() -> dict:
    if not config.MANIFEST_PATH.exists():
        return {"version": MANIFEST_VERSION, "files": {}}
    with open(config.MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    """Write atomically: a crash mid-write can't leave a half-written manifest."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.MANIFEST_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    os.replace(tmp, config.MANIFEST_PATH)


def list_documents() -> list[Path]:
    """All supported files under docs/raw (subfolders included), sorted."""
    return sorted(
        p for p in config.RAW_DOCS_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in config.SUPPORTED_EXTENSIONS
    )


def rel_name(path: Path) -> str:
    """Manifest key: path relative to docs/raw, with forward slashes."""
    return path.relative_to(config.RAW_DOCS_DIR).as_posix()


@dataclass
class ScanResult:
    new: dict[str, str] = field(default_factory=dict)            # name -> hash
    unchanged: dict[str, str] = field(default_factory=dict)      # name -> hash
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (recorded, current)
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Safe to ingest only if no approved file has been modified."""
        return not self.changed


def scan() -> ScanResult:
    """Hash every document and compare against the manifest. Writes nothing."""
    recorded = load_manifest()["files"]
    result = ScanResult()
    seen = set()

    for path in list_documents():
        name = rel_name(path)
        seen.add(name)
        digest = sha256_file(path)
        if name not in recorded:
            result.new[name] = digest
        elif recorded[name]["sha256"] == digest:
            result.unchanged[name] = digest
        else:
            result.changed[name] = (recorded[name]["sha256"], digest)

    result.missing = sorted(set(recorded) - seen)
    return result


def record(files: dict[str, str]) -> None:
    """Add or overwrite manifest entries (name -> hash)."""
    manifest = load_manifest()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for name, digest in files.items():
        manifest["files"][name] = {
            "sha256": digest,
            "size_bytes": (config.RAW_DOCS_DIR / name).stat().st_size,
            "recorded_at": now,
        }
    save_manifest(manifest)


def print_report(result: ScanResult) -> None:
    for name, digest in result.new.items():
        print(f"[NEW]        {name}  {digest[:12]}...")
    for name, digest in result.unchanged.items():
        print(f"[UNCHANGED]  {name}  {digest[:12]}...")
    for name, (old, cur) in result.changed.items():
        print(f"[CHANGED]    {name}  recorded {old[:12]}...  now {cur[:12]}...")
    for name in result.missing:
        print(f"[MISSING]    {name}  (in manifest, file not found)")


def main() -> int:
    parser = argparse.ArgumentParser(description="SHA-256 integrity gate for docs/raw")
    parser.add_argument("--accept", metavar="FILE",
                        help="re-approve a changed file after human review (name relative to docs/raw)")
    parser.add_argument("--forget", metavar="FILE",
                        help="remove a deleted file from the manifest (its chunks are purged on next ingest)")
    args = parser.parse_args()
    config.ensure_dirs()

    if args.forget:
        manifest = load_manifest()
        if manifest["files"].pop(args.forget, None) is None:
            print(f"{args.forget} is not in the manifest.")
            return 1
        save_manifest(manifest)
        print(f"Forgot {args.forget}. Run python -m rag.vectorstore to purge its chunks.")
        return 0

    if args.accept:
        path = (config.RAW_DOCS_DIR / args.accept).resolve()
        # Only files inside docs/raw with a supported type can be approved.
        if config.RAW_DOCS_DIR.resolve() not in path.parents \
                or path.suffix.lower() not in config.SUPPORTED_EXTENSIONS:
            print(f"Refusing: {args.accept} is not a supported file inside docs/raw")
            return 1
        if not path.is_file():
            print(f"No such file: {path}")
            return 1
        name = rel_name(path)
        record({name: sha256_file(path)})
        print(f"Re-approved {name}. Its old chunks must be re-ingested.")
        return 0

    result = scan()
    print_report(result)

    if not result.ok:
        print("\nREFUSED: approved document(s) modified since they were recorded:")
        for name in result.changed:
            print(f"  - {name}")
        print("Possible knowledge-base poisoning. Nothing was ingested or recorded.")
        print("If the change is legitimate, review the file, then run:")
        print("  python -m rag.integrity --accept <file>")
        return 1

    if result.new:
        record(result.new)
    print(f"\nOK: {len(result.new)} new, {len(result.unchanged)} unchanged, "
          f"{len(result.missing)} missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
