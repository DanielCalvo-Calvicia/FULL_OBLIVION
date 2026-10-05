"""The final environment of one service, and where each value came from."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResolvedEnv:
    values: dict[str, str] = field(default_factory=dict)
    layer_of: dict[str, str] = field(default_factory=dict)  # variable -> the layer (a file or "computed") that set it
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def set(self, layer: str, key: str, value: str) -> None:
        self.values[key] = value
        self.layer_of[key] = layer
