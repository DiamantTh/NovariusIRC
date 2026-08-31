"""Connection-local IRCv3 BATCH tracking."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IRCBatch:
    reference: str
    batch_type: str
    parameters: tuple[str, ...] = ()
    parent: str | None = None


class BatchTracker:
    """Track bounded active batches and their optional nesting."""

    def __init__(self, maximum_active: int = 64) -> None:
        if maximum_active < 1:
            raise ValueError("maximum active IRC batches must be positive")
        self.maximum_active = maximum_active
        self.active: dict[str, IRCBatch] = {}

    def clear(self) -> None:
        self.active.clear()

    def start(self, params: tuple[str, ...], parent: str | None = None) -> IRCBatch:
        if len(params) < 2 or not params[0].startswith("+"):
            raise ValueError("Malformed IRC BATCH start")
        reference = params[0][1:]
        batch_type = params[1]
        self._validate_reference(reference)
        if not batch_type or any(character.isspace() for character in batch_type):
            raise ValueError("Invalid IRC BATCH type")
        if reference in self.active:
            raise ValueError(f"IRC BATCH reference already active: {reference}")
        if len(self.active) >= self.maximum_active:
            raise ValueError("Too many active IRC batches")
        if parent is not None and parent not in self.active:
            raise ValueError(f"Unknown parent IRC BATCH reference: {parent}")
        batch = IRCBatch(reference, batch_type, tuple(params[2:]), parent)
        self.active[reference] = batch
        return batch

    def end(self, params: tuple[str, ...]) -> IRCBatch:
        if len(params) != 1 or not params[0].startswith("-"):
            raise ValueError("Malformed IRC BATCH end")
        reference = params[0][1:]
        self._validate_reference(reference)
        if any(batch.parent == reference for batch in self.active.values()):
            raise ValueError(f"IRC BATCH has active child: {reference}")
        try:
            return self.active.pop(reference)
        except KeyError as exc:
            raise ValueError(f"Unknown IRC BATCH reference: {reference}") from exc

    def get(self, reference: str | None) -> IRCBatch | None:
        return self.active.get(reference) if reference else None

    @staticmethod
    def _validate_reference(reference: str) -> None:
        if (
            not reference
            or len(reference.encode("utf-8")) > 128
            or any(character.isspace() for character in reference)
        ):
            raise ValueError("Invalid IRC BATCH reference")
