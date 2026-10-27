"""The shape of a batched backfill: id ranges of a fixed size, so no single transaction touches the whole table."""

from __future__ import annotations

from collections.abc import Iterator


def id_ranges(first_id: int, last_id: int, batch_size: int) -> Iterator[tuple[int, int]]:
    """Inclusive (first, last) id ranges of `batch_size` ids from `first_id` up to and including `last_id`."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    start = first_id
    while start <= last_id:
        yield start, min(start + batch_size - 1, last_id)
        start += batch_size
