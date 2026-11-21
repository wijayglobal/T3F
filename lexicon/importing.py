"""Shared bulk-import steps: find suggestion ids for (term, tamil) pairs and record attestations."""
from .models import Attestation, Region, Suggestion

CHUNK = 900  # SQLite caps the number of query parameters


def suggestion_ids(pairs, term_ids):
    """{(term_text, tamil): suggestion_id} for the common-region rows of `pairs`.
    term_ids maps term text -> id."""
    wanted = {(term_ids[t], ta): (t, ta) for t, ta in pairs if t in term_ids}
    tids = sorted({tid for tid, _ in wanted})
    out = {}
    for i in range(0, len(tids), CHUNK):
        rows = Suggestion.objects.filter(term_id__in=tids[i : i + CHUNK], region=Region.COMMON)
        for tid, ta, sid in rows.values_list("term_id", "tamil", "id"):
            if (tid, ta) in wanted:
                out[wanted[(tid, ta)]] = sid
    return out


def attest(attestations, batch_size=2000):
    """Insert or refresh Attestation rows (one per suggestion and source)."""
    Attestation.objects.bulk_create(
        attestations,
        update_conflicts=True,
        unique_fields=["suggestion", "source"],
        update_fields=["source_kind", "source_url", "source_ref", "license", "sense", "domain", "register", "note"],
        batch_size=batch_size,
    )
