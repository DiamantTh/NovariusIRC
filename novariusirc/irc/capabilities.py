"""IRCv3 capability state and wire helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilityToken:
    """One capability token from a CAP message."""

    name: str
    value: str | None = None
    disabled: bool = False


@dataclass(frozen=True)
class CapabilityProfile:
    """Capabilities requested normally and experimental drafts enabled explicitly."""

    standard: tuple[str, ...] = ()
    drafts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        invalid_drafts = [name for name in self.drafts if not name.startswith("draft/")]
        if invalid_drafts:
            raise ValueError(
                "Experimental IRC capabilities must use the draft/ namespace: "
                + ", ".join(invalid_drafts)
            )

    @property
    def requested(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.standard, *self.drafts)))


def parse_capability_token(value: str) -> CapabilityToken:
    """Parse a capability token while keeping its name case-sensitive."""
    disabled = value.startswith("-")
    raw = value[1:] if disabled else value
    name, separator, token_value = raw.partition("=")
    if not name or any(character.isspace() for character in name):
        raise ValueError(f"Invalid IRC capability token: {value!r}")
    return CapabilityToken(name, token_value if separator else None, disabled)


def cap_req_lines(capabilities: list[str], maximum_bytes: int = 510) -> list[str]:
    """Split capability requests into valid IRC wire lines."""
    lines: list[str] = []
    chunk: list[str] = []
    for capability in capabilities:
        parse_capability_token(capability)
        candidate = " ".join([*chunk, capability])
        line = f"CAP REQ :{candidate}"
        if len(line.encode()) > maximum_bytes:
            if not chunk:
                raise ValueError(f"IRC capability is too long: {capability!r}")
            lines.append(f"CAP REQ :{' '.join(chunk)}")
            chunk = [capability]
        else:
            chunk.append(capability)
    if chunk:
        lines.append(f"CAP REQ :{' '.join(chunk)}")
    return lines


@dataclass
class CapabilityState:
    """Connection-local offered, active, and pending capabilities."""

    offered: dict[str, str | None] = field(default_factory=dict)
    active: set[str] = field(default_factory=set)
    pending: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self.offered.clear()
        self.active.clear()
        self.pending.clear()

    def advertise(self, values: list[str]) -> list[CapabilityToken]:
        tokens = [parse_capability_token(value) for value in values]
        for token in tokens:
            self.offered[token.name] = token.value
        return tokens

    def wanted(self, configured: list[str]) -> list[str]:
        return [
            capability
            for capability in configured
            if capability in self.offered
            and capability not in self.active
            and capability not in self.pending
        ]

    def request(self, capabilities: list[str]) -> None:
        self.pending.update(capabilities)

    def acknowledge(
        self, values: list[str]
    ) -> tuple[set[str], set[str]]:
        enabled: set[str] = set()
        disabled: set[str] = set()
        for token in (parse_capability_token(value) for value in values):
            self.pending.discard(token.name)
            if token.disabled:
                self.active.discard(token.name)
                disabled.add(token.name)
            else:
                self.active.add(token.name)
                enabled.add(token.name)
        return enabled, disabled

    def reject(self, values: list[str]) -> set[str]:
        rejected = {parse_capability_token(value).name for value in values}
        self.pending.difference_update(rejected)
        return rejected

    def remove(self, values: list[str]) -> set[str]:
        removed = {parse_capability_token(value).name for value in values}
        for capability in removed:
            self.offered.pop(capability, None)
            self.active.discard(capability)
            self.pending.discard(capability)
        return removed
