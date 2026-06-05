from dataclasses import dataclass

from composition_root.dependencies.stt_dependency import (
    STTDependency,
    generate_stt_dependency,
)
from runtime.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class Container:
    name: str
    stt_dependency: STTDependency


def BuildContainer(name: str) -> Container:
    logger.info("Building container '%s'.", name)
    stt_dep = generate_stt_dependency()
    logger.info("STT dependency generated for container '%s'.", name)
    
    return Container(
        name=name,
        stt_dependency=stt_dep
    )
