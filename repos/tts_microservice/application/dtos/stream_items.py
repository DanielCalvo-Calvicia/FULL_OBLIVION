from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class AudioSegmentEnd:
    """Marks the end of one logical synthesized audio output."""


@dataclass(slots=True, frozen=True)
class AudioStreamError:
    """Carries a recoverable stream error to HTTP consumers."""

    code: str
    message: str
    recoverable: bool = True
