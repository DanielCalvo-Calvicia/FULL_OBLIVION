# Live Flow Tests

This folder contains opt-in checks that exercise multiple real services through
the brain orchestration layer.

## `test_live_health_flow.py`

- `test_live_health_for_each_microservice`
  calls `BrainService.check_integrations()` through real configured adapters
  and asserts microphone, STT, TTS, and speaker are available.

## `test_live_microphone_to_stt_flow.py`

- `test_live_microphone_to_stt_flow_opens_text_stream_from_real_microphone_audio`
  opens the real microphone stream, starts STT `/process/stream/set`, opens STT
  `/process/stream/get` after the shared stream is initialized, and keeps
  consuming that single STT SSE stream until it closes. If the SSE stream closes,
  the test does not reopen `/get`; it parks forever so you can inspect the
  closed state until you explicitly stop the debug session, interrupt pytest,
  or terminate the process.

## `test_live_microphone_to_stt_manual_speech.py`

- `test_live_microphone_to_stt_transcribes_speech_from_real_microphone`
  opens the real microphone stream, starts STT `/process/stream/set`, opens STT
  `/process/stream/get`, and requires one non-empty transcription segment. This
  is a manual diagnostic test: run it when you are ready to speak into the
  microphone. It is guarded by both `RUN_LIVE_MICROSERVICE_TESTS=1` and
  `RUN_LIVE_MIC_STT_SPEECH_TEST=1`. The wait timeout defaults to 20 seconds and
  can be changed with `LIVE_MIC_STT_SPEECH_TIMEOUT_SECONDS`.

## `test_live_stt_to_tts_flow.py`

- `test_live_stt_to_tts_flow_connects_real_stt_text_output_to_tts_text_input`
  sends bounded silent audio into real STT through `/process/stream/set`, opens
  `/process/stream/get`, and attaches the resulting text stream to real TTS
  text input. This proves the live `stt -> tts` stream boundary accepts the
  decoupled STT connection even when silence produces no text.

## `test_live_tts_to_speaker_flow.py`

- `test_live_tts_to_speaker_flow_forwards_real_tts_audio_to_speaker`
  sends diagnostic text to real TTS, opens real TTS audio output, and forwards
  that audio into the real speaker service.
- `test_live_debug_text_variable_streams_through_real_tts_to_speaker`
  creates a real async text stream from the debug text variable
  `"Hello world, Hello world,Hello world,"`, posts it to real TTS
  `/process/stream/set`, opens real TTS audio output, and forwards that audio
  stream into the real speaker service.

## `test_live_voice_pipeline.py`

- `test_live_voice_pipeline_runs_real_mic_to_stt_to_tts_to_speaker_attachment`
  runs the public live full voice pipeline with a bounded timeout.

## `attachments/`

- Contains live Flow4 attachment tests for text playback through real
  TTS/speaker and batch transcription through real STT.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/flows
```

Run only the streamed text-variable TTS-to-speaker debug check:

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/flows/test_live_tts_to_speaker_flow.py::test_live_debug_text_variable_streams_through_real_tts_to_speaker -vv
```

Run the manual microphone speech transcription check:

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
$env:RUN_LIVE_MIC_STT_SPEECH_TEST='1'
python -m pytest tests/live/flows/test_live_microphone_to_stt_manual_speech.py -vv
```
