import sounddevice as sd
import asyncio
from application.ports.adapter_outbound_port import AdapterOutboundPort
from application.dtos.adapter_outbound_dtos import InitOutboundAdapterDto
from application.dtos.services_dtos import PlaybackStreamRequestDto, PlaybackStreamResponseDto, SpeakerCleanupResponseDto
from runtime.logger import get_logger

logger = get_logger("infrastructure.outbound")

class SoundDeviceSpeakerAdapter(AdapterOutboundPort):
    def __init__(self, config: InitOutboundAdapterDto):
        self.config = config
        self.device_index: int | None = None
        self.stream: sd.RawOutputStream | None = None
        self._playback_task: asyncio.Task[None] | None = None
        self._is_playing: bool = False
        logger.info(
            "Initializing SoundDeviceSpeakerAdapter: configured_device_index=%s target_keywords=%s",
            config.device_index,
            config.target_keywords,
        )
        
        self._initialize_device()

    def _initialize_device(self) -> None:
        try:
            logger.info("Initializing sounddevice output device selection.")
            self.device_index = self._select_output_device()
            logger.info(f"sounddevice initialized. Selected output device index: {self.device_index}")
        except Exception as e:
            logger.critical(f"Failed to query sounddevice output devices: {e}")
            raise RuntimeError(f"sounddevice bootstrap failed: {e}")

    def _select_output_device(self) -> int:
        if self.config.device_index is not None:
            logger.info("Using explicitly configured sounddevice output device index: %s", self.config.device_index)
            return self.config.device_index

        devices = sd.query_devices()
        keywords = self.config.target_keywords
        logger.info("Auto-selecting sounddevice output device from %s discovered devices.", len(devices))

        # Auto-discovery based on keywords (matching microphones/speakers in this ecosystem)
        for i, info in enumerate(devices):
            try:
                name = str(info.get("name", ""))
                max_output = int(info.get("max_output_channels", 0))
                
                if max_output > 0:
                    logger.trace("Device ID %s candidate: '%s' Channels: %s", i, name, max_output)
                    if any(kw.lower() in name.lower() for kw in keywords):
                        logger.info(f"Auto-selected device ID {i}: '{name}' based on keywords.")
                        return i
            except Exception as e:
                logger.warning(f"Error querying device ID {i}: {e}")

        # Fallback to system default output
        try:
            default_output = sd.default.device[1]
            if default_output is not None:
                default_info = sd.query_devices(default_output)
                logger.warning(f"No keyword match found. Falling back to default ID {default_output}: '{default_info.get('name')}'")
                return default_output
            else:
                raise RuntimeError("No OS default output device configured")
        except Exception as e:
            raise RuntimeError(f"No valid output devices discovered: {e}")

    def _open_device_stream(self, sample_rate: int, channels: int) -> None:
        if self.stream is not None:
            logger.info("Existing sounddevice stream detected. Stopping and closing before opening a new stream.")
            try:
                self.stream.stop()
                self.stream.close()
                logger.info("Previous sounddevice stream closed.")
            except Exception as e:
                logger.warning("Failed to close previous sounddevice stream cleanly: %s", e)
            self.stream = None

        logger.info(f"Opening sounddevice RawOutputStream (Device: {self.device_index}, Rate: {sample_rate}, Channels: {channels})")
        
        try:
            self.stream = sd.RawOutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype='int16',
                device=self.device_index
            )
            self.stream.start()
            logger.info("sounddevice RawOutputStream started at requested sample rate: %s", sample_rate)
        except Exception as e:
            logger.warning("Failed to open at %sHz: %s. Retrying with system default 44100Hz.", sample_rate, e)
            try:
                self.stream = sd.RawOutputStream(
                    samplerate=44100,
                    channels=channels,
                    dtype='int16',
                    device=self.device_index
                )
                self.stream.start()
                logger.info("sounddevice RawOutputStream started with fallback sample rate: 44100")
            except Exception as e2:
                logger.error(f"Failed standard rate fallback: {e2}")
                raise e2

    async def play_stream(self, request: PlaybackStreamRequestDto) -> PlaybackStreamResponseDto:
        logger.info(
            "Outbound playback requested: sample_rate=%s channels=%s",
            request.sample_rate,
            request.channels,
        )
        # Prevent simultaneous playback tasks overriding the same stream
        if self._is_playing:
            logger.info("Existing playback is active. Cleaning it up before starting new playback.")
            await self.cleanup_playback_task()

        try:
            self._open_device_stream(request.sample_rate, request.channels)
        except Exception as e:
            logger.error(f"Failed to open hardware device: {e}")
            response = PlaybackStreamResponseDto(success=False, message=f"Hardware stream open failure: {e}")
            if request.setup_future is not None and not request.setup_future.done():
                request.setup_future.set_result(response)
            return response

        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._is_playing = True
        queued_chunks = 0
        queued_bytes = 0
        written_chunks = 0
        written_bytes = 0
        stream_error: Exception | None = None

        async def _audio_player_worker() -> None:
            """Background worker consuming raw bytes and writing them via OS calls."""
            nonlocal written_chunks, written_bytes
            logger.info("Audio player worker started.")
            while self._is_playing:
                try:
                    chunk = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if chunk is None:  # Stop sentinel
                    queue.task_done()
                    logger.info("Audio player worker received stop sentinel.")
                    break

                if self.stream is not None:
                    try:
                        # Write audio chunk inside threadpool executor to avoid event loop stalls
                        await asyncio.to_thread(self.stream.write, chunk)
                        written_chunks += 1
                        written_bytes += len(chunk)
                    except Exception as e:
                        logger.error(f"sounddevice write exception: {e}")
                        break

                queue.task_done()
            logger.info(
                "Audio player worker stopped: written_chunks=%s written_bytes=%s",
                written_chunks,
                written_bytes,
            )

        # Bootstrap non-blocking player
        self._playback_task = asyncio.create_task(_audio_player_worker())
        logger.info("Outbound playback worker task created.")
        if request.setup_future is not None and not request.setup_future.done():
            request.setup_future.set_result(PlaybackStreamResponseDto(success=True, message="Playback stream started"))

        try:
            # Consume incoming generator stream and feed playback queue
            async for chunk in request.audio_stream:
                if not self._is_playing:
                    logger.info("Playback flag turned off while consuming inbound audio stream.")
                    break
                if chunk:
                    queued_chunks += 1
                    queued_bytes += len(chunk)
                    await queue.put(chunk)
        except Exception as e:
            stream_error = e
            logger.error(
                "Error consuming inbound audio generator stream: type=%s message=%r",
                type(e).__name__,
                str(e),
            )
        finally:
            logger.info(
                "Finished consuming inbound audio stream: queued_chunks=%s queued_bytes=%s",
                queued_chunks,
                queued_bytes,
            )
            # Put sentinel block and join
            await queue.put(None)
            try:
                await asyncio.wait_for(queue.join(), timeout=3.0)
                logger.info("Playback queue drained successfully.")
            except asyncio.TimeoutError:
                logger.warning("Playback queue cleanup timed out. Truncating.")
            
            self._is_playing = False

        logger.info(
            "Playback session finalized: queued_chunks=%s queued_bytes=%s written_chunks=%s written_bytes=%s",
            queued_chunks,
            queued_bytes,
            written_chunks,
            written_bytes,
        )
        if stream_error is not None:
            return PlaybackStreamResponseDto(success=False, message=str(stream_error))
        return PlaybackStreamResponseDto(success=True, message="Playback session finalized successfully")

    async def cleanup_playback_task(self) -> None:
        logger.info("Cleaning up active playback task.")
        self._is_playing = False
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                logger.info("Playback task cancelled.")
                pass
            self._playback_task = None
        else:
            logger.info("No active playback task required cancellation.")

    async def cleanup(self) -> SpeakerCleanupResponseDto:
        logger.info("Cleaning up sounddevice resources...")
        await self.cleanup_playback_task()

        if self.stream is not None:
            try:
                if self.stream.active:
                    self.stream.stop()
                    logger.info("Active sounddevice stream stopped.")
                self.stream.close()
                logger.info("sounddevice stream closed.")
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            self.stream = None

        logger.info("Sounddevice cleanup completed.")
        return SpeakerCleanupResponseDto(success=True)
