from collections.abc import AsyncIterator


async def byte_stream(chunks: tuple[bytes, ...]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def text_stream(chunks: tuple[str, ...]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk
