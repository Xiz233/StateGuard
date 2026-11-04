"""Benchmark adapters advertise evidence and verifier capabilities here."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping

from ..verification.contracts import EvidenceSource


@dataclass(frozen=True)
class EnvironmentCapabilities:
    available_sources: frozenset[EvidenceSource]
    supported_verifiers: frozenset[str] = field(default_factory=frozenset)
    action_effect_channels: Mapping[str, frozenset[EvidenceSource]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        sources = frozenset(EvidenceSource(value) for value in self.available_sources)
        verifiers = frozenset(str(value) for value in self.supported_verifiers)
        channels = {
            str(action_type): frozenset(EvidenceSource(value) for value in values)
            for action_type, values in self.action_effect_channels.items()
        }
        object.__setattr__(self, "available_sources", sources)
        object.__setattr__(self, "supported_verifiers", verifiers)
        object.__setattr__(self, "action_effect_channels", MappingProxyType(channels))

    @classmethod
    def screenshot_only(cls) -> "EnvironmentCapabilities":
        return cls(available_sources=frozenset({EvidenceSource.SCREENSHOT}))

    def has_sources(self, sources: Iterable[EvidenceSource]) -> bool:
        return set(sources) <= self.available_sources

    def missing_sources(
        self, sources: Iterable[EvidenceSource]
    ) -> frozenset[EvidenceSource]:
        return frozenset(set(sources) - self.available_sources)

    def supports_verifier(self, verifier_id: str | None) -> bool:
        return verifier_id is None or verifier_id in self.supported_verifiers

    def sources_for_action(self, action_type: str) -> frozenset[EvidenceSource]:
        return self.action_effect_channels.get(action_type, frozenset())

    def to_dict(self) -> dict:
        return {
            "available_sources": sorted(source.value for source in self.available_sources),
            "supported_verifiers": sorted(self.supported_verifiers),
            "available_actions": sorted(self.action_effect_channels),
        }
