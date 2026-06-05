from dataclasses import dataclass
from typing import Any

from composition_root.config import AppConfig
from composition_root.dependencies.brain_dependency import BrainDependency, generate_brain_dependency


@dataclass(frozen=True, slots=True)
class Container:
    name: str
    config: AppConfig
    brain_dependency: BrainDependency
    background_tasks: tuple[Any, ...] = ()


def BuildContainer(name: str, config: AppConfig) -> Container:
    return Container(
        name=name,
        config=config,
        brain_dependency=generate_brain_dependency(config),
    )
