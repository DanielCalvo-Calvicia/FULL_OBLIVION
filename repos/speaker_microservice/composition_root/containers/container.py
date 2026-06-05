from dataclasses import dataclass
from composition_root.dependencies.speaker_dependency import SpeakerDependency, generate_speaker_dependency
from runtime.logger import get_logger

logger = get_logger("container")

@dataclass(slots=True, frozen=True)
class Container:
    speaker_dependency: SpeakerDependency

def BuildContainer(name: str) -> Container:
    """Instantiate and compile all system dependency trees."""
    logger.info("Building container: %s", name)
    speaker_dep = generate_speaker_dependency()
    container = Container(speaker_dependency=speaker_dep)
    logger.info("Container built: %s", name)
    return container
