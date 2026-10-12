"""Build a one-page text PDF for adversarial testing (no extra libraries).

Lines starting with "HIDDEN:" are drawn in white -- invisible to a person
looking at the slide, but extracted by pypdf like any other text. That is
how real indirect-prompt-injection payloads hide inside documents.

Usage:
    python tests/make_test_pdf.py OUT.pdf "Title" "line 1" "HIDDEN:secret line" ...
"""
import sys


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: str, lines: list[str]) -> None:
    ops = ["BT", "/F1 13 Tf", "16 TL", "50 750 Td"]
    for line in lines:
        hidden = line.startswith("HIDDEN:")
        text = line[len("HIDDEN:"):] if hidden else line
        ops += ["1 1 1 rg" if hidden else "0 0 0 rg", f"({_escape(text)}) Tj", "T*"]
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    with open(path, "wb") as f:
        f.write(out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    make_pdf(sys.argv[1], sys.argv[2:])
    print(f"wrote {sys.argv[1]}")
