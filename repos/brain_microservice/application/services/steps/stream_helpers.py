import asyncio
from collections.abc import AsyncIterator

from domain.console import console_log


async def finite_silence_audio_stream(sample_rate: int, seconds: int) -> AsyncIterator[bytes]:
    total_bytes = sample_rate * seconds * 2
    chunk_size = 1024
    sent = 0
    while sent < total_bytes:
        size = min(chunk_size, total_bytes - sent)
        sent += size
        yield b"\0" * size


async def read_one_chunk(name: str, byte_stream: AsyncIterator[bytes], timeout_seconds: float) -> None:
    try:
        chunk = await asyncio.wait_for(byte_stream.__anext__(), timeout=timeout_seconds)
        if not chunk:
            raise RuntimeError(f"{name} stream probe returned an empty chunk")
        console_log("brain-service", "stream probe received first chunk", stream=name, bytes=len(chunk))
    finally:
        close = getattr(byte_stream, "aclose", None)
        if close is not None:
            await close()
