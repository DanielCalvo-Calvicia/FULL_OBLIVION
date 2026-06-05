from dataclasses import dataclass

from composition_root.dependencies.tts_dependency import (
    TTSDependency,
    generate_tts_dependency,
)
from infrastructure.logger import get_logger

logger = get_logger(__name__)

@dataclass(slots=True, frozen=True)
class Container:
    name: str
    tts_dependency: TTSDependency


def BuildContainer(name: str) -> Container:
    logger.info("BuildContainer started name=%s", name)
    tts_dep = generate_tts_dependency()
    container = Container(
        name=name,
        tts_dependency=tts_dep
    )
    logger.info("BuildContainer finished name=%s", name)
    return container
