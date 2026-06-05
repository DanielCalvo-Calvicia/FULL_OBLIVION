# Mock Project Tests

This folder covers project behavior that does not belong to one external
microservice adapter.

## `test_brain_service.py`

- `test_transcribe_batch_delegates_to_stt`
  verifies batch transcription delegates to STT and maps the result.

- `test_transcribe_microphone_collects_limited_segments`
  verifies microphone transcription starts and stops the microphone, streams
  into STT, and respects the segment limit.

- `test_play_text_sends_tts_audio_to_speaker`
  verifies text is sent to TTS and resulting audio reaches the speaker.

- `test_voice_pipeline_connects_mic_to_stt_to_tts_to_speaker`
  verifies the public full-pipeline method with fake ports.

## `test_config.py`

- `test_load_config_accepts_full_endpoint_urls`
  verifies full endpoint URLs are normalized into base URL plus path.

- `test_load_config_normalizes_debug_environment_alias`
  verifies `APP_ENV=debug` maps to development.

## `test_environment.py`

- Tests environment normalization, runtime environment precedence, invalid
  environment fallback, launch profile loading, and process environment
  precedence.

## `test_console.py`

- Tests logger visibility rules for development, staging, and production.

## Run

```powershell
python -m pytest tests/mock/project
```
