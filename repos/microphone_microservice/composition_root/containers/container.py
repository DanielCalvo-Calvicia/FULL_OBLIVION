from dataclasses import dataclass

from composition_root.dependencies.microphone_dependency import (
    generate_microphone_dependency,
    MicrophoneDependency
)
from composition_root.runtime.logger import get_logger


logger = get_logger("container")

@dataclass(slots=True, frozen=True)
class Container:
    microphone_dependency: MicrophoneDependency

def BuildContainer(name: str) -> Container:
    logger.info("Building dependency container", name=name)
    microphone_dependency = generate_microphone_dependency(
        default_fallback_rate=16000,
        target_keywords=[]
    )

    logger.info("Dependency container built")
    return Container(
        microphone_dependency=microphone_dependency
    )
