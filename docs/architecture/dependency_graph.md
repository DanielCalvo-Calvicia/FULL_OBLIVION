# FULL_OBLIVION Dependency Graph

## Full Voice Pipeline

```mermaid
flowchart LR
    User([User]) -->|speaks| MIC[Microphone :8000]
    MIC -->|PCM events| BRAIN[Brain :7999]
    BRAIN -->|audio stream| STT[STT :8001]
    STT -->|text events| BRAIN
    BRAIN -->|text stream| TTS[TTS :8002]
    TTS -->|audio events| BRAIN
    BRAIN -->|audio stream| SPK[Speaker :8003]
    SPK -->|plays audio| User
```

## Startup Dependencies

```mermaid
flowchart TD
    MIC[Configured microphone URL healthy] --> BRAIN[Brain startup]
    STT[Configured STT URL healthy] --> BRAIN
    TTS[Configured TTS URL healthy] --> BRAIN
    SPK[Configured speaker URL healthy] --> BRAIN
    BRAIN --> PREFLIGHT[Brain startup preflight]
    PREFLIGHT --> PIPELINE[Voice pipeline background task]
```

## Service Selection Expansion

```mermaid
flowchart TD
    SELECT_BRAIN[User enables brain profile] --> BRAIN[brain]
    BRAIN -. configured URL .-> MIC[microphone local or remote]
    BRAIN -. configured URL .-> STT[stt local or remote]
    BRAIN -. configured URL .-> TTS[tts local or remote]
    BRAIN -. configured URL .-> SPK[speaker local or remote]

    SELECT_STT[User enables stt profile] --> STT_ONLY[stt only]
    SELECT_TTS[User enables tts profile] --> TTS_ONLY[tts only]
    SELECT_AUDIO[User enables audio profile] --> MIC_AUDIO[microphone]
    SELECT_AUDIO --> SPK_AUDIO[speaker]
```

## Runtime Dependency Matrix

| Service | Startup Dependencies | Runtime Dependencies |
|---|---|---|
| brain | configured service URLs | HTTP access to microphone, stt, tts, and speaker, local or remote |
| microphone | none | PortAudio, host input device |
| stt | none | OpenAI API or faster-whisper model cache |
| tts | none | OpenAI API or pyttsx3/espeak |
| speaker | none | PortAudio, host output device |

## Conflict Points

| Resource | Services | Mitigation |
|---|---|---|
| Host ports `7999-8003` | all | Change `.env` host port mappings |
| Container port `8000` | microphone | Fixed by service source; do not add another internal `8000` service with the same name/port expectation |
| Audio input device | microphone | Run one microphone instance per physical input |
| Audio output device | speaker | Run one speaker instance per physical output |
| STT model cache | stt | Use named volume `stt-model-cache` |
