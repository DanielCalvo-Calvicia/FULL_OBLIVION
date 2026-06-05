# Live TTS Tests

## `test_live_tts.py`

- `test_live_tts_stream_accepts_text_and_emits_audio`
  sends test text to the real TTS service, opens the audio stream, and waits for
  one non-empty audio chunk.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/external_microservices/tts
```
