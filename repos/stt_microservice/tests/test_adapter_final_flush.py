import asyncio

import numpy as np

from application.dtos.adapter_outbound_dtos import ProcessStreamRequestDto
from infrastructure.outbound.local_stt_adapter import AsyncTextStream
from infrastructure.outbound.openai_stt_adapter import _AsyncOpenAITextStream


async def _audio_stream(chunks: list[bytes]):
    for chunk in chunks:
        yield chunk


def _pcm_chunk(value: int, samples: int = 1024) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


class FakeLocalModel:
    language = None

    def transcribe(self, audio_data, **kwargs):
        self.language = kwargs["language"]

        class Segment:
            text = " final local text"

        return [Segment()], None


def test_local_stream_flushes_final_buffer_when_audio_input_ends() -> None:
    async def run() -> str:
        request = ProcessStreamRequestDto(
            audio_stream=_audio_stream([_pcm_chunk(10000)]),
            sample_rate=16000,
            chunk_size=1024,
            silence_threshold=150,
            silence_limit_seconds=2.0,
        )
        model = FakeLocalModel()
        stream = AsyncTextStream(request, model, "es")
        text = await stream.__anext__()
        assert model.language == "es"
        return text

    assert asyncio.run(run()) == "final local text"


def test_openai_stream_flushes_final_buffer_when_audio_input_ends() -> None:
    async def run() -> str:
        request = ProcessStreamRequestDto(
            audio_stream=_audio_stream([]),
            sample_rate=16000,
            chunk_size=1024,
            silence_threshold=150,
            silence_limit_seconds=2.0,
        )
        stream = _AsyncOpenAITextStream(request, "test-key")
        stream._is_speaking = True
        stream.audio_buffer.extend(_pcm_chunk(1000))

        async def fake_transcribe() -> str:
            stream._reset_buffers()
            return "final openai text"

        stream._transcribe_utterance = fake_transcribe
        return await stream.__anext__()

    assert asyncio.run(run()) == "final openai text"
