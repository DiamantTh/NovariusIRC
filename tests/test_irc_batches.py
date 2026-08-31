from __future__ import annotations

import pytest

from novariusirc.irc.batches import BatchTracker


def test_batch_tracker_supports_nested_lifecycles() -> None:
    tracker = BatchTracker()
    outer = tracker.start(("+outer", "netjoin", "irc.example"))
    inner = tracker.start(("+inner", "labeled-response"), parent="outer")

    assert outer.parameters == ("irc.example",)
    assert inner.parent == "outer"
    with pytest.raises(ValueError, match="active child"):
        tracker.end(("-outer",))
    assert tracker.end(("-inner",)) == inner
    assert tracker.end(("-outer",)) == outer
    assert not tracker.active


def test_batch_tracker_rejects_unknown_duplicate_and_unbounded_state() -> None:
    tracker = BatchTracker(maximum_active=1)
    tracker.start(("+one", "example"))
    with pytest.raises(ValueError, match="already active"):
        tracker.start(("+one", "example"))
    with pytest.raises(ValueError, match="Too many"):
        tracker.start(("+two", "example"))
    with pytest.raises(ValueError, match="Unknown"):
        BatchTracker().end(("-missing",))
