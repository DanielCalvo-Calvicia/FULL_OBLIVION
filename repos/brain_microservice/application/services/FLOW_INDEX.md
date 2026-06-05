# Brain Service Flow Index

This service is organized around the voice pipeline executor:

1. `service.py`: public service facade.
2. `pipeline.py`: voice pipeline executor.
3. `steps/`: isolated voice pipeline steps.

## Voice Pipeline

Main file:
`application/services/pipeline.py`

The voice pipeline is the microphone -> STT -> TTS -> speaker flow.
The service file is only the executor. It initializes `VoicePipelineContext`,
then runs isolated steps in order. Steps do not call each other and do not know
which step comes next. All cross-step state moves through the context.

Phase order:

1. Health.
2. Open external GET streams.
3. Create internal bridge streams.
4. Open external SET streams.
5. Merge external streams into internal streams.

Step files:

1. `steps/health_check/step1_health_check.py`
2. `steps/stream_get/step2_get_mic_stream.py`
3. `steps/stream_set/step3_set_stt_stream.py`
4. `steps/stream_get/step4_get_stt_stream.py`
5. `steps/stream_set/step5_set_tts_stream.py`
6. `steps/stream_get/step6_get_tts_stream.py`
7. `steps/stream_set/step7_set_speaker_stream.py`
8. `steps/stream_internal/step8_mic_to_stt.py`
9. `steps/stream_internal/step9_stt_to_tts.py`
10. `steps/stream_internal/step10_tts_to_speaker.py`

1. Check health availability. `health`
   - Calls microphone, STT, TTS, and speaker `check_health()`.
   - Stops immediately if any required adapter is unavailable.

2. Get microphone output stream. `stream initialization`
   - Opens microphone audio output with `microphone_port.start_stream()`.
   - Produces `MicrophoneStreamResponseDto.audio_stream`.

3. Prepare and start STT input stream connector. `stream set`
   - Creates the STT input connector stream.
   - Starts `stt_port.set_stream()` in a background task.

4. Get STT text output stream. `stream get`
   - Opens STT text output with `stt_port.get_stream()`.
   - Retries briefly if the STT SET stream has started but the provider has not exposed the output stream yet.
   - Produces `STTStreamResponseDto.text_stream`.

5. Prepare and start TTS input stream connector. `stream set`
   - Creates the TTS input connector stream.
   - Wraps the connector with `limit_and_count_text_stream()` so empty text is skipped and `max_text_segments` is enforced.
   - Starts `tts_port.set_text_stream()` in a background task.

6. Get TTS audio output stream. `stream get`
   - Opens TTS output with `tts_port.get_stream()`.

7. Prepare and start speaker playback connector. `stream set`
   - Creates the speaker input connector stream.
   - Starts `speaker_port.play_stream()` immediately.

8. Bridge microphone output into the internal STT input stream. `stream internal`
   - Constructor receives `mic_stream_out` and `stt_stream_in`.
   - Owns `mic_stream_out`, `stt_stream_in`, and `AsyncStreamPipe("mic-to-stt-audio")`.
   - Starts copying microphone audio into the internal stream.
   - Internal output uses standard stream events and completes with `payload.output_bytes_base64`.

9. Bridge STT output into the internal TTS input stream. `stream internal`
   - Constructor receives `stt_stream_out` and `tts_stream_in`.
   - Owns `stt_stream_out`, `tts_stream_in`, and `AsyncStreamPipe("stt-to-tts-text")`.
   - Starts copying STT text output into the internal stream.
   - Internal output uses standard stream events and completes with `payload.output`.

10. Bridge TTS output into the internal speaker input stream. `stream internal`
   - Constructor receives `tts_stream_out` and `speaker_stream_in`.
   - Owns `tts_stream_out`, `speaker_stream_in`, and `AsyncStreamPipe("tts-to-speaker-audio")`.
   - Starts copying TTS audio output into the internal stream.
   - Internal output uses standard stream events and completes with `payload.output_bytes_base64`.

## Text Playback

Main file:
`application/services/service.py`

1. Set TTS input stream with a single text string.
2. Get TTS audio output stream.
3. Set speaker input stream with TTS output stream.
4. Return speaker playback result.

## Microphone Transcription

Main file:
`application/services/service.py`

1. Get microphone output stream.
2. Set STT input stream with microphone output stream.
3. Get STT text output stream.
4. Collect text segments.
5. Finish or cancel STT input forwarding.
6. Return collected transcription text.

## Batch Transcription

Main file:
`application/services/service.py`

1. Send complete audio bytes to STT batch endpoint.
2. Return STT batch text response.
