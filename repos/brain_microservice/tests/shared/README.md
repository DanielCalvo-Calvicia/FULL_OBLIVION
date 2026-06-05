# Shared Test Utilities

This folder contains helper code used by tests in other folders. It should not
contain pytest test cases.

## `streams.py`

- `byte_stream(chunks)`
  creates an async byte iterator from a tuple of byte chunks. Tests use this to
  simulate microphone, TTS, and speaker streams.

- `text_stream(chunks)`
  creates an async text iterator from a tuple of strings. Tests use this to
  simulate STT output and streamed TTS input.

## `fakes.py`

- `DiagnosticMicrophone`
  fake microphone port with configurable health availability and audio chunks.
  It records start requests and stop calls so flow tests can assert cleanup and
  stream settings.

- `DiagnosticSTT`
  fake STT port with configurable health availability and text chunks. It
  records stream and batch requests, and captures audio bytes received from
  microphone flow tests.

- `DiagnosticTTS`
  fake TTS port with configurable health availability and audio chunks. It
  records set/get requests and captures text received from STT flow tests.

- `DiagnosticSpeaker`
  fake speaker port with configurable health availability. It records playback
  requests and captures audio bytes received from TTS flow tests.

- `build_brain_service(...)`
  convenience factory that wires the fake ports into a `BrainService`.

- `SERVICE_NAMES`
  canonical service ordering used by health-flow tests.

## `live_microservices.py`

- `LiveMicroservices`
  builds the real HTTP adapters from current config and wires them into a
  `BrainService`. Live tests use this helper to avoid duplicating adapter setup.
  Its `close()` method closes all owned HTTP clients.
