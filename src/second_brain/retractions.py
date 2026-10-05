"""``sb check --retractions``: ask Crossref again for notices about every paper with a DOI.

Crossref includes Retraction Watch data in ``updated-by``: retractions,
withdrawals, expressions of concern and corrections. New notices are stored in
the record (``updates``) and retractions/concerns become flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ingest.metadata import MetadataClient, crossref_updates, flags_from_updates
from .library import InvalidDocument, Library
from .models import Update


@dataclass
class Notice:
    citekey: str
    title: str
    updates: list[Update]
    new: list[Update] = field(default_factory=list)

    @property
    def retracted(self) -> bool:
        return "retracted" in flags_from_updates(self.updates)


def check_updates(lib: Library, client: MetadataClient) -> list[Notice]:
    """Papers that have any notice; records are updated when Crossref reports new ones."""
    notices = []
    for doc in lib.iter_papers():
        if isinstance(doc, InvalidDocument) or not doc.meta.doi:
            continue
        paper = doc.meta
        message = client.crossref_work(paper.doi, refresh=True)
        if message is None:
            continue
        updates = [Update.model_validate(u) for u in crossref_updates(message)]
        known = {(u.type, u.doi) for u in paper.updates}
        new = [u for u in updates if (u.type, u.doi) not in known]
        if new:
            flags = sorted(set(paper.flags) | set(flags_from_updates(updates)))
            lib.write_paper(paper.model_copy(update={"updates": updates, "flags": flags}), doc.body)
        if updates:
            notices.append(Notice(paper.citekey, paper.title, updates, new))
    return notices
