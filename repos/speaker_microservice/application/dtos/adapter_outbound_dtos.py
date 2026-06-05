from dataclasses import dataclass

@dataclass(slots=True, frozen=True)
class InitOutboundAdapterDto:
    """Configures the hardware audio output device properties."""
    device_index: int | None = None
    target_keywords: tuple[str, ...] = ("i2s", "hw", "default", "sysdefault")
