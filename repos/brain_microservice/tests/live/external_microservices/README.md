# Live External Microservice Tests

This folder contains opt-in checks for each real external microservice.

## Service Folders

- `microphone/`: opens the real microphone stream and reads one audio chunk.
- `stt/`: sends finite silent audio to the real STT service.
- `tts/`: sends text to the real TTS service and reads one audio chunk.
- `speaker/`: sends finite silent audio to the real speaker service.

## Run

```powershell
$env:RUN_LIVE_MICROSERVICE_TESTS='1'
python -m pytest tests/live/external_microservices
```
