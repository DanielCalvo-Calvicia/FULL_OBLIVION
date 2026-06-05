# Mock Flow Tests

This folder tests brain orchestration with fake ports. These tests do not call
real microservices.

## `test_health_flow.py`

- `test_health_reports_each_microservice_for_every_availability_combination`
  runs all 16 up/down combinations for microphone, STT, TTS, and speaker. It
  verifies that health results are independent and ordered consistently.

## `test_microphone_to_stt_flow.py`

- `test_mic_to_stt_flow_forwards_microphone_audio_and_stream_settings`
  verifies the `mic -> stt` connection forwards audio and stream settings.

## `test_stt_to_tts_flow.py`

- `test_stt_to_tts_flow_forwards_clean_limited_text_segments`
  verifies the `stt -> tts` connection strips text, skips empty segments, and
  enforces the max segment limit.

## `test_tts_to_speaker_flow.py`

- `test_tts_to_speaker_flow_forwards_tts_audio_and_playback_settings`
  verifies the `tts -> speaker` connection forwards audio, sample rate, and
  channel settings.

## `attachments/`

- Contains Flow4 attachment tests for no-speech short circuit behavior,
  microphone cleanup on STT attachment failure, and batch-only STT attachment
  behavior.

## `test_voice_pipeline.py`

- `test_full_voice_pipeline_connects_mic_to_stt_to_tts_to_speaker`
  verifies the full fake-backed pipeline from microphone audio to speaker
  playback.

## Run

```powershell
python -m pytest tests/mock/flows
```
