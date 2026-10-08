"""``sb pdf link``: find, in other folders, the PDFs this machine is missing.

A record knows its PDF's sha256 and size, so a PDF is recognised wherever it is
(``~/Zotero/storage``, a backup, ``pdfs/`` under an old citekey after
``sb edit --rekey``). Only files of the right size are hashed, so large folders
are cheap to scan. The matches go through the normal ingestion, which copies
them into ``pdfs/`` (the originals are never moved) and puts an original in place
of another version.
"""

from __future__ import annotations

from pathlib import Path

from ..library import Library
from .dedupe import LibraryIndex
from .extract import sha256_file


def wanted_pdfs(lib: Library, index: LibraryIndex) -> dict[str, int]:
    """sha256 → size of the PDFs (articles and supplements) missing from ``pdfs/``, or whose
    local file is another version."""
    wanted: dict[str, int] = {}
    for paper in index.papers.values():
        local = lib.pdfs_dir / f"{paper.citekey}.pdf"
        if paper.pdf and (not local.exists() or "pdf_version_mismatch" in paper.flags):
            wanted[paper.pdf.sha256] = paper.pdf.size_bytes
        for supplement in paper.supplements:
            if not lib.supplement_pdf(paper.citekey, supplement.id).exists():
                wanted[supplement.sha256] = supplement.size_bytes
    return wanted


def find_pdfs(folders: list[Path], wanted: dict[str, int]) -> list[Path]:
    """One file per wanted sha256 found under ``folders`` (recursively)."""
    sizes = set(wanted.values())
    found: dict[str, Path] = {}
    for folder in folders:
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() != ".pdf" or not path.is_file():
                continue
            if path.stat().st_size not in sizes:
                continue
            sha = sha256_file(path)
            if sha in wanted and sha not in found:
                found[sha] = path
    return list(found.values())
