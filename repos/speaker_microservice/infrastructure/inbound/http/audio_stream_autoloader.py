import asyncio
import httpx
from typing import AsyncIterator

from application.dtos.adapter_inbound_dtos import StartSpeakerStreamRequestDto
from application.ports.adapter_inbound_port import AdapterInboundPort
from runtime.logger import get_logger

logger = get_logger("infrastructure.inbound.autoloader")

class AudioStreamAutoloader:
    def __init__(self, stream_url: str, inbound_adapter: AdapterInboundPort):
        self.stream_url = stream_url
        self.inbound_adapter = inbound_adapter
        self._task: asyncio.Task[None] | None = None
        logger.info("AudioStreamAutoloader initialized for stream URL: %s", stream_url)

    def start(self) -> None:
        if self._task is None or self._task.done():
            logger.info("Starting audio stream autoloader worker task.")
            self._task = asyncio.create_task(self._worker())
        else:
            logger.info("Autoloader start requested, but worker is already running.")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            logger.info("Stopping audio stream autoloader worker task.")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("Autoloader worker task cancelled.")
                pass
            self._task = None
        else:
            logger.info("Autoloader stop requested, but no active worker task exists.")

    async def _worker(self) -> None:
        method = "POST"
        while True:
            try:
                logger.info("Connecting to audio stream at %s via %s.", self.stream_url, method)
                # We use timeout=None to allow an infinitely long stream
                async with httpx.AsyncClient(timeout=None) as client:
                    stream_context = (
                        client.stream(method, self.stream_url, json={})
                        if method == "POST"
                        else client.stream(method, self.stream_url)
                    )
                    async with stream_context as response:
                        if response.status_code == 405 and method == "POST":
                            logger.warning("Autoload method %s not allowed. Falling back to GET.", method)
                            method = "GET"
                            continue
                            
                        response.raise_for_status()
                        logger.info("Autoload stream connected: %s", self.stream_url)
                        chunk_count = 0
                        total_bytes = 0
                        
                        async def stream_generator() -> AsyncIterator[bytes]:
                            nonlocal chunk_count, total_bytes
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    chunk_count += 1
                                    total_bytes += len(chunk)
                                yield chunk
                                
                        dto = StartSpeakerStreamRequestDto(
                            audio_stream=stream_generator(),
                            sample_rate=24000,
                            channels=1
                        )
                        
                        speaker_response = await self.inbound_adapter.play(dto)
                        logger.info(
                            "Autoload playback completed: success=%s message=%s chunks=%s bytes=%s",
                            speaker_response.success,
                            speaker_response.message,
                            chunk_count,
                            total_bytes,
                        )
                                
            except httpx.RequestError as e:
                logger.warning("Autoload connection error: %s. Reconnecting in 5s.", e)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("Autoloader worker cancelled.")
                break
            except Exception as e:
                logger.exception("Autoloader unexpected error: %s. Reconnecting in 5s.", e)
                await asyncio.sleep(5)
