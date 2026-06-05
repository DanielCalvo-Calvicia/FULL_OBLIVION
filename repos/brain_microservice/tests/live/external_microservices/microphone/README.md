# Live Microphone Tests

## `test_live_microphone.py`

- `test_live_microphone_stream_can_open_and_emit_audio`
  calls the real configured microphone service, opens the `/start` stream,
  waits for one non-empty audio chunk, then attempts to stop the stream.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/external_microservices/microphone
```
