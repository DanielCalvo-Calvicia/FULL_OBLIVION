# Mock External Microservice Tests

This folder tests the outbound HTTP adapter contracts without starting real
microservices. Each service folder uses `httpx.MockTransport` to verify what
the brain would send over HTTP and how adapter responses are mapped back into
DTOs.

## Service Folders

- `microphone/`: tests `HttpMicrophoneAdapter`.
- `stt/`: tests `HttpSTTAdapter`.
- `tts/`: tests `HttpTTSAdapter`.
- `speaker/`: tests `HttpSpeakerAdapter`.

## Run

```powershell
python -m pytest tests/mock/external_microservices
```
