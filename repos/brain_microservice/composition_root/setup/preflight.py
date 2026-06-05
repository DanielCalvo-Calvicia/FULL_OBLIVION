import asyncio

from application.services.service import BrainService
from composition_root.config import AppConfig
from domain.console import console_log


class StartupPreflightError(RuntimeError):
    pass


async def run_startup_preflight(service: BrainService, config: AppConfig) -> None:
    if not config.startup_preflight_enabled:
        console_log("preflight", "startup preflight disabled")
        return

    console_log(
        "preflight",
        "starting mandatory startup preflight before inbound adapter opens",
        timeout_seconds=config.startup_preflight_timeout_seconds,
    )

    try:
        await asyncio.wait_for(
            _run_checks(service, config),
            timeout=config.startup_preflight_timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise StartupPreflightError(
            f"Startup preflight timed out after {config.startup_preflight_timeout_seconds} seconds"
        ) from exc

    console_log("preflight", "startup preflight completed successfully")


async def _run_checks(service: BrainService, config: AppConfig) -> None:
    await _wait_until_microservices_are_ready(service, config)


async def _wait_until_microservices_are_ready(service: BrainService, config: AppConfig) -> None:
    deadline = asyncio.get_running_loop().time() + config.startup_preflight_timeout_seconds
    attempt = 0
    last_unavailable = ""

    while True:
        attempt += 1
        console_log("preflight", "checking all external microservices are fully loaded", attempt=attempt)
        health = await service.check_integrations()
        unavailable = [status for status in health.services if not status.is_available]
        if not unavailable:
            console_log("preflight", "all external microservices are active and ready", attempts=attempt)
            return

        last_unavailable = "; ".join(f"{status.name}: {status.detail}" for status in unavailable)
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise StartupPreflightError(
                f"Startup preflight failed: microservices not fully loaded: {last_unavailable}"
            )

        sleep_seconds = min(config.microservice_ready_poll_interval_seconds, remaining)
        console_log(
            "preflight",
            "microservices not ready yet; waiting",
            unavailable=last_unavailable,
            sleep_seconds=round(sleep_seconds, 2),
        )
        await asyncio.sleep(sleep_seconds)
