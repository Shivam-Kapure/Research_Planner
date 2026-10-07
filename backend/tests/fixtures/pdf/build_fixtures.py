"""Builds the PDF fixtures in this folder (real PDFs with a text layer, standard Helvetica).

Run from backend/:  uv run python tests/fixtures/pdf/build_fixtures.py
Output is deterministic, so rebuilding produces identical files.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent

PAPER_PAGES = [
    [
        "Sleep Deprivation and Memory Consolidation in Adults",
        "Abstract",
        "We examined how one night of total sleep deprivation affects next-day recall",
        "in a randomised crossover study of 40 healthy adults aged 18 to 35 years.",
        "Introduction",
        "Sleep is thought to support the consolidation of declarative memories, but",
        "the size of the effect in adults remains debated across laboratory studies.",
    ],
    [
        "Methods",
        "Participants learned 60 word pairs in the evening and were tested the next",
        "morning after either a normal night of sleep or a night of supervised waking.",
        "Recall was scored blind to condition and analysed with a mixed effects model.",
    ],
    [
        "Results",
        "Recall was 20% lower after a night without sleep than after normal sleep.",
        "The effect was larger for weakly encoded pairs than for strongly encoded ones,",
        "suggesting that sleep preferentially stabilises fragile memory traces.",
        "Discussion",
        "These findings support an active role for sleep in memory consolidation.",
    ],
    [
        "References",
        "Smith J, Lee K. Sleep and memory: a review. Journal of Sleep Research. 2019.",
        "Garcia M. Total sleep deprivation and recall. Neuropsychologia. 2021.",
        "Chen W, Patel R. Encoding strength and consolidation. Memory. 2020.",
    ],
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[str]]) -> bytes:
    """Minimal valid PDF 1.4: catalog, page tree, Helvetica font, one content stream per page."""
    count = len(pages)
    page_ids = [4 + 2 * i for i in range(count)]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: (
            f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {count} >>"
        ).encode(),
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for lines, page_id in zip(pages, page_ids, strict=True):
        content = (
            "BT /F1 11 Tf 14 TL 50 760 Td "
            + " ".join(f"({_escape(line)}) Tj T*" for line in lines)
            + " ET"
        )
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        ).encode()
        objects[page_id + 1] = (
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream"
        ).encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number in range(1, len(objects) + 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


if __name__ == "__main__":
    (HERE / "paper.pdf").write_bytes(build_pdf(PAPER_PAGES))
    # Pages with no text layer: what a scanned (image-only) PDF looks like to pypdf.
    (HERE / "scanned.pdf").write_bytes(build_pdf([[], [], []]))
    print("wrote paper.pdf and scanned.pdf")
