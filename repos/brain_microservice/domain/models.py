from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    name: str
    is_available: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    transcript: str
    playback_success: bool

