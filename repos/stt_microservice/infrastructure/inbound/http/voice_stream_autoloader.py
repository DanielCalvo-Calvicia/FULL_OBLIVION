import asyncio
import httpx
from typing import AsyncIterator

from application.ports.adapter_inbound_port import AdapterInboundPort
from application.dtos.adapter_inbound_dtos import ProcessStreamRequestDto
from runtime.logger import get_logger

logger = get_logger(__name__)


class VoiceStreamAutoloader:
    def __init__(self, stream_url: str, inbound_adapter: AdapterInboundPort) -> None:
        self.stream_url = stream_url
        self.inbound_adapter = inbound_adapter
        self._task: asyncio.Task[None] | None = None
        logger.info("VoiceStreamAutoloader initialized for stream URL %s.", stream_url)

    def start(self) -> None:
        if self._task is None or self._task.done():
            logger.info("Creating VoiceStreamAutoloader worker task.")
            self._task = asyncio.create_task(self._worker())
        else:
            logger.info("VoiceStreamAutoloader worker task is already running.")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            logger.info("Cancelling VoiceStreamAutoloader worker task.")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("VoiceStreamAutoloader worker task cancelled.")
                pass
            self._task = None
        else:
            logger.info("VoiceStreamAutoloader stop requested with no active task.")

    async def _worker(self) -> None:
        method = "POST"
        logger.info("VoiceStreamAutoloader worker loop started.")
        while True:
            try:
                logger.info("Connecting to voice stream at %s via %s.", self.stream_url, method)
                # We use timeout=None to allow an infinitely long stream
                async with httpx.AsyncClient(timeout=None) as client:
                    stream_context = (
                        client.stream(method, self.stream_url, json={})
                        if method == "POST"
                        else client.stream(method, self.stream_url)
                    )
                    async with stream_context as response:
                        if response.status_code == 405 and method == "POST":
                            logger.warning("Voice stream rejected POST with 405. Falling back to GET.")
                            method = "GET"
                            continue
                            
                        response.raise_for_status()
                        logger.info("Connected to voice stream at %s with status %s.", self.stream_url, response.status_code)
                        
                        async def stream_generator() -> AsyncIterator[bytes]:
                            async for chunk in response.aiter_bytes():
                                logger.debug("Autoloader received stream chunk: bytes=%s.", len(chunk))
                                yield chunk
                                
                        dto = ProcessStreamRequestDto(
                            audio_stream=stream_generator(),
                            sample_rate=16000,
                            chunk_size=1024,
                            silence_threshold=150,
                            silence_limit_seconds=2.0
                        )
                        
                        stt_response = await self.inbound_adapter.process_stream(dto)
                        
                        async for text in stt_response.text_stream:
                            if text:
                                logger.info("Autoload transcription received: text_length=%s.", len(text))
                                logger.info("Autoload transcription: %s", text)
                                
            except httpx.RequestError as e:
                logger.warning("Voice stream connection error: %s. Reconnecting in 5 seconds.", e)
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("VoiceStreamAutoloader worker loop cancelled.")
                break
            except Exception:
                logger.exception("Unexpected VoiceStreamAutoloader error. Reconnecting in 5 seconds.")
                await asyncio.sleep(5)
