import sys
from typing import Optional, AsyncIterator
import sounddevice as sd
import asyncio

# Import your new DTO here
from application.dtos.adapter_outbound_dtos import (
    InitOutboundAdapterDto,
    StartMicrophoneStreamRequestDto,
    StartMicrophoneStreamResponseDto,
    StopMicrophoneStreamRequestDto,
    StopMicrophoneStreamResponseDto,
    MicrophoneAvailabilityRequestDto,
    MicrophoneAvailabilityResponseDto,
)
from application.ports.adapter_outbound_port import AdapterOutboundPort
from composition_root.runtime.logger import get_logger

import numpy as np


logger = get_logger("outbound")
stream_logger = get_logger("audio-stream")

class SoundDeviceAsyncStream(AsyncIterator[bytes]):

    def __init__(self, stream: sd.RawInputStream, chunk_size: int, input_channels: int = 1):
        self._stream = stream
        self._chunk_size = chunk_size
        self._input_channels = input_channels
        self._closed = False
        stream_logger.info(
            "Initialized",
            chunk_size=chunk_size,
            input_channels=input_channels,
            stream_active=getattr(stream, "active", "unknown"),
        )

        # Telemetry counters
        self._chunk_count: int = 0
        self._total_bytes: int = 0
        self._overflow_count: int = 0

    def __aiter__(self):
        stream_logger.trace("__aiter__ called")
        return self

    async def __anext__(self) -> bytes:
        if self._closed:
            stream_logger.trace("__anext__ called after closed; stopping iteration")
            raise StopAsyncIteration

        try:
            stream_logger.trace("Reading chunk", chunk_number=self._chunk_count + 1)
            data, overflowed = await asyncio.to_thread(
                self._stream.read, 
                self._chunk_size
            )
            stream_logger.trace(
                "Raw read returned",
                overflowed=overflowed,
                bytes=len(bytes(data)),
            )

            chunk = bytes(data)

            # Convert stereo -> mono without audioop
            if self._input_channels > 1:
                stream_logger.trace("Downmixing channels to mono", input_channels=self._input_channels)
                samples = np.frombuffer(chunk, dtype=np.int16)

                # Reshape into [frames, channels]
                samples = samples.reshape(-1, self._input_channels)

                # Mix down channels (equivalent to 0.5, 0.5)
                mono = samples.mean(axis=1)

                # Convert back to int16 PCM bytes
                chunk = mono.astype(np.int16).tobytes()

            # ── Telemetry (every chunk, single-line overwrite) ──
            self._chunk_count += 1
            self._total_bytes += len(chunk)
            if overflowed:
                self._overflow_count += 1

            self._log_telemetry(chunk, overflowed)

            return chunk

        except asyncio.CancelledError:
            stream_logger.warn("Streaming response was cancelled by client/server")
            self._closed = True
            raise
        except Exception as error:
            stream_logger.error("Microphone stream read failed", error=repr(error))
            self._closed = True
            raise RuntimeError("Microphone stream read failed") from error

    def _log_telemetry(self, chunk: bytes, overflowed: bool) -> None:
        """Overwrite a single console line with live audio telemetry."""
        samples = np.frombuffer(chunk, dtype=np.int16)

        # RMS volume (root mean square)
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

        # Convert RMS to dB (relative to int16 max = 32767)
        rms_db = 20 * np.log10(rms / 32767) if rms > 0 else -float("inf")

        # Peak amplitude
        peak = int(np.max(np.abs(samples)))

        # Visual volume bar (0–30 chars)
        bar_len = min(30, int((rms / 32767) * 30 * 5))  # x5 gain for visibility
        bar = "█" * bar_len + "░" * (30 - bar_len)

        overflow_flag = " ⚠ OVF" if overflowed else ""

        line = (
            f"\r  🎤 #{self._chunk_count:<6}  "
            f"|{bar}|  "
            f"RMS: {rms:>7.1f} ({rms_db:>6.1f} dB)  "
            f"Peak: {peak:>5}  "
            f"{len(chunk):>5}B"
            f"{overflow_flag}"
        )

        # Pad with spaces to clear any leftover characters from previous line
        sys.stdout.write(line.ljust(120))
        sys.stdout.flush()

    async def close(self):
        stream_logger.info("close requested", closed=self._closed)
        if not self._closed:
            # Move to a new line so the close summary doesn't overwrite the live meter
            print(
                f"\n  🎤 Stream closed  |  "
                f"total chunks: {self._chunk_count}  |  "
                f"total bytes: {self._total_bytes}  |  "
                f"overflows: {self._overflow_count}"
            )
        self._closed = True


class MicrophoneAdapter(AdapterOutboundPort):

    default_fallback_rate: int
    target_keywords: list[str]

    started = False
    mic_sample_rate: Optional[int] = None
    mic_chunk_size: Optional[int] = None
    mic_channels: Optional[int] = None

    device_index: Optional[int] = None
    audio_stream: Optional[sd.RawInputStream] = None

    loop_stream: Optional[SoundDeviceAsyncStream] = None

    # --- UPDATED INIT TO ACCEPT THE DTO ---
    def __init__(self, config: InitOutboundAdapterDto):
        super().__init__()

        # Store configuration primitives internally
        self.default_fallback_rate = config.default_fallback_rate
        self.target_keywords = config.target_keywords
        logger.info(
            "MicrophoneAdapter initialized",
            default_fallback_rate=self.default_fallback_rate,
            target_keywords=self.target_keywords,
        )

    @property
    def sample_rate(self) -> int:
        if self.mic_sample_rate is None:
            logger.warn("sample_rate requested but no stream is active")
            raise RuntimeError("Microphone sample rate is not available")
        logger.trace("sample_rate requested", value=self.mic_sample_rate)
        return self.mic_sample_rate

    @property
    def chunk_size(self) -> int:
        if self.mic_chunk_size is None:
            logger.warn("chunk_size requested but no stream is active")
            raise RuntimeError("Microphone chunk size is not available")
        logger.trace("chunk_size requested", value=self.mic_chunk_size)
        return self.mic_chunk_size

    async def start_stream(self, request: StartMicrophoneStreamRequestDto) -> StartMicrophoneStreamResponseDto:
        logger.info(
            "start_stream received",
            sample_rate=request.sample_rate,
            channels=request.channels,
            chunk_size=request.chunk_size,
            started=self.started,
        )
        if request.sample_rate <= 0 or request.channels <= 0 or request.chunk_size <= 0:
            logger.warn("start_stream rejected invalid parameters")
            raise ValueError("Invalid microphone stream parameters")
        
        if self.started:
            logger.warn("start_stream rejected because stream is already started")
            raise RuntimeError("Microphone stream already started")
        
        sample_rate = request.sample_rate
        channels = request.channels
        chunk_size = request.chunk_size

        self.mic_sample_rate = sample_rate
        self.mic_channels = channels
        self.mic_chunk_size = chunk_size

        try:
            logger.info("Finding microphone device")
            self.device_index = self.find_microphone_index()
            logger.info("Using microphone device index", device_index=self.device_index)
            
            device_info = sd.query_devices(self.device_index)
            logger.trace("Selected device info", device_info=device_info)
            # Use our DTO fallback setting if default_samplerate is missing
            default_rate = int(device_info.get('default_samplerate', self.default_fallback_rate))
            
            if sample_rate != default_rate:
                logger.warn(
                    "Requested sample rate may not be supported",
                    requested_rate=sample_rate,
                    device_default_rate=default_rate,
                )
                
        except Exception as e:
            logger.error("Error finding microphone", error=str(e))
            raise RuntimeError("No microphone devices available")

        try:
            logger.info(
                "Opening RawInputStream",
                samplerate=sample_rate,
                blocksize=chunk_size,
                device=self.device_index,
                channels=channels,
                dtype="int16",
            )
            self.audio_stream = sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=chunk_size,
                device=self.device_index,
                channels=channels,
                dtype='int16'
            )
            self.audio_stream.start()
            logger.info("RawInputStream started", active=self.audio_stream.active)
        except Exception as e:
            logger.warn(
                "Failed to open requested rate; retrying with hardware default",
                requested_rate=sample_rate,
                default_rate=default_rate,
                error=repr(e),
            )
            sample_rate = default_rate
            self.mic_sample_rate = sample_rate
            try:
                logger.info(
                    "Retrying RawInputStream with hardware default",
                    samplerate=sample_rate,
                    blocksize=chunk_size,
                    device=self.device_index,
                    channels=channels,
                    dtype="int16",
                )
                self.audio_stream = sd.RawInputStream(
                    samplerate=sample_rate,
                    blocksize=chunk_size,
                    device=self.device_index,
                    channels=channels,
                    dtype='int16'
                )
                self.audio_stream.start()
                logger.info("RawInputStream retry started", active=self.audio_stream.active)
            except Exception as e2:
                if channels == 1:
                    logger.warn("Mono failed; retrying with stereo", error=repr(e2))
                    channels = 2
                    self.mic_channels = channels
                    logger.info(
                        "Retrying RawInputStream in stereo",
                        samplerate=sample_rate,
                        blocksize=chunk_size,
                        device=self.device_index,
                        channels=channels,
                        dtype="int16",
                    )
                    self.audio_stream = sd.RawInputStream(
                        samplerate=sample_rate,
                        blocksize=chunk_size,
                        device=self.device_index,
                        channels=channels,
                        dtype='int16'
                    )
                    self.audio_stream.start()
                    logger.info("Stereo RawInputStream started", active=self.audio_stream.active)
                else:
                    logger.error("RawInputStream retry failed", error=repr(e2))
                    raise e2

        if self.audio_stream is None:
            raise RuntimeError("Microphone stream could not be opened")

        logger.info("Creating async stream wrapper")
        self.loop_stream = SoundDeviceAsyncStream(
            stream=self.audio_stream,
            chunk_size=chunk_size,
            input_channels=channels
        )
        self.started = True
        logger.info(
            "Runtime state set",
            started=self.started,
            device_index=self.device_index,
            sample_rate=sample_rate,
            chunk_size=chunk_size,
            channels=channels,
        )
        
        logger.info(
            "Microphone successfully started",
            device_index=self.device_index,
            sample_rate=sample_rate,
            channels=channels,
            channel_mode="Mono" if channels == 1 else "Stereo",
            chunk_size=chunk_size,
        )

        return StartMicrophoneStreamResponseDto(
            stream=self.loop_stream,
            sample_rate=sample_rate,
        )

    async def stop_stream(self, request: StopMicrophoneStreamRequestDto) -> StopMicrophoneStreamResponseDto:
        logger.info("stop_stream received", started=self.started)
        if not self.started:
            logger.info("stop_stream no active stream; returning success")
            return StopMicrophoneStreamResponseDto(success=True)
        try:
            if self.loop_stream is not None:
                logger.info("Closing async stream wrapper")
                await self.loop_stream.close()
                self.loop_stream = None

            if self.audio_stream is not None:
                logger.info("Closing RawInputStream", active=self.audio_stream.active)
                if self.audio_stream.active:
                    logger.info("Stopping RawInputStream")
                    self.audio_stream.stop()
                logger.info("Closing RawInputStream")
                self.audio_stream.close()
                self.audio_stream = None

            logger.info("Clearing runtime state")
            self.started = False
            self.device_index = None
            self.mic_sample_rate = None
            self.mic_chunk_size = None
            self.mic_channels = None

            logger.info("stop_stream completed")
            return StopMicrophoneStreamResponseDto(success=True)
        except Exception as error:
            logger.error("stop_stream failed", error=repr(error))
            raise RuntimeError(f"Failed to stop microphone stream: {error}") from error

    async def is_available(self, request: MicrophoneAvailabilityRequestDto) -> MicrophoneAvailabilityResponseDto:
        logger.info("is_available requested", started=self.started)
        return MicrophoneAvailabilityResponseDto(is_available=self.started)
    def find_microphone_index(self) -> int:
        """Programmatically find the best microphone index"""
        devices = sd.query_devices()
        logger.info("Scanning for microphones", devices_found=len(devices))
        
        for i, info in enumerate(devices):
            if int(info.get('max_input_channels', 0)) > 0:
                name: str = str(info.get('name'))
                channels = int(info.get('max_input_channels', 0))
                default_rate = info.get('default_samplerate', 'unknown')
                logger.trace(
                    "Found input device",
                    device_id=i,
                    name=name,
                    max_input_channels=channels,
                    default_samplerate=default_rate,
                )
                
                # Uses the keywords parsed directly from our DTO
                if any(key.lower() in name.lower() for key in self.target_keywords):
                    logger.info("Auto-selected keyword match", name=name, device_id=i)
                    return i

        try:
            default_input = sd.default.device[0]
            logger.info("No keyword match; using OS default input", default_input=default_input)
            if default_input is not None:
                default_info = sd.query_devices(default_input)
                logger.info("Using default input device", name=default_info["name"])
                return default_input
            else:
                raise RuntimeError("No default input device configured in OS")
        except Exception:
            logger.warn("No microphones found")
            raise RuntimeError("No microphone devices available")
