from __future__ import annotations

import pytest

from novariusirc.irc.capabilities import (
    CapabilityProfile,
    CapabilityState,
    cap_req_lines,
    parse_capability_token,
)


def test_capability_profile_keeps_drafts_explicit() -> None:
    profile = CapabilityProfile(
        standard=("server-time", "message-tags"),
        drafts=("draft/chathistory",),
    )
    assert profile.requested == (
        "server-time",
        "message-tags",
        "draft/chathistory",
    )

    with pytest.raises(ValueError, match="draft/ namespace"):
        CapabilityProfile(drafts=("chathistory",))


def test_capability_state_tracks_lifecycle_and_values() -> None:
    state = CapabilityState()
    state.advertise(["sasl=PLAIN,EXTERNAL", "server-time"])
    assert state.offered == {
        "sasl": "PLAIN,EXTERNAL",
        "server-time": None,
    }
    assert state.wanted(["server-time", "away-notify"]) == ["server-time"]

    state.request(["server-time"])
    enabled, disabled = state.acknowledge(["server-time"])
    assert enabled == {"server-time"}
    assert not disabled
    assert state.active == {"server-time"}
    assert not state.pending

    assert state.remove(["server-time"]) == {"server-time"}
    assert not state.active
    assert "server-time" not in state.offered


def test_capability_tokens_remain_case_sensitive() -> None:
    token = parse_capability_token("-Example.NET/Feature=value")
    assert token.name == "Example.NET/Feature"
    assert token.value == "value"
    assert token.disabled


def test_capability_request_lines_respect_wire_limit() -> None:
    capabilities = ["a" * 250, "b" * 250, "c"]
    lines = cap_req_lines(capabilities)
    assert all(len(line.encode()) <= 510 for line in lines)
    assert lines == [f"CAP REQ :{' '.join(capabilities[:2])}", "CAP REQ :c"]

    with pytest.raises(ValueError, match="too long"):
        cap_req_lines(["x" * 502])
