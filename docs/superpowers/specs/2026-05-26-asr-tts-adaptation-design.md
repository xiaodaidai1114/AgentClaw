# ASR/TTS Adaptation Design

Date: 2026-05-26

## Background

fast_agent needs a channel-independent way to adapt speech-to-text and text-to-speech. The goal is to avoid writing ASR/TTS handling separately for every IM channel or every provider. Channel adapters should only handle platform audio download/upload details; model adapters should only handle provider API differences.

The design references Dify core and `dify-official-plugins`, but does not copy Dify's plugin marketplace. We only borrow the stable model-type abstraction:

- `speech2text`: audio bytes -> text
- `tts`: text + voice -> audio bytes stream

## Dify Reference Summary

Dify core exposes ASR/TTS as model types:

- ASR receives a multipart audio `file`, validates audio type/size, finds the default `speech2text` model, calls `invoke_speech2text(file=...)`, and returns `{"text": "..."}`.
- TTS receives `text` and optional `voice`, finds the default `tts` model, chooses a voice when missing, calls `invoke_tts(content_text=..., voice=...)`, and returns audio bytes, usually as a stream.
- Voices are queried from the default TTS model through `get_tts_voices(language)`.

Dify plugin invocation uses a lower-level payload:

```text
ASR:
{
  provider,
  model_type: "speech2text",
  model,
  credentials,
  file: "<hex audio bytes>"
}
-> { result: "recognized text" }

TTS:
{
  provider,
  model_type: "tts",
  model,
  credentials,
  content_text,
  voice
}
-> streaming chunks: { result: "<hex audio bytes>" }
```

Important issues to avoid from Dify:

- Dify names ASR temp audio as `temp.mp3` even when the real input format is different.
- Dify's TTS HTTP response often uses fixed `audio/mpeg`, while some providers may produce another format.

fast_agent should keep `mime_type`, `filename`/`ext`, and TTS `output_mime_type` in its own audio abstraction.

## Provider Findings

`dify-official-plugins` supports many ASR/TTS providers, but most fit a few protocol families.

| Provider | ASR | TTS | Shape | Recommendation |
| --- | --- | --- | --- | --- |
| `openai` | yes | yes | OpenAI audio SDK | P0 built-in |
| `openai_api_compatible` | yes | yes | OpenAI-compatible HTTP/API | P0 built-in |
| `azure_openai` | yes | yes | Azure OpenAI audio deployment | P0/P1, reuse OpenAI adapter |
| `groq` | yes | no | OpenAI-compatible ASR | P1, reuse compatible adapter |
| `aihubmix` | yes | yes | OpenAI-like aggregator | P1 |
| `cometapi` | yes | yes | OpenAI-like aggregator | P1 |
| `deerapi` | yes | yes | OpenAI-like aggregator | P1 |
| `siliconflow` | yes | yes | Mostly OpenAI-compatible | P1 |
| `tongyi` | yes | yes | DashScope SDK/API | P1/P2 |
| `minimax` | no | yes | Dedicated TTS HTTP stream | P1/P2 |
| `fishaudio` | yes | yes | Fish Audio SDK | P2 |
| `xinference` | yes | yes | Self-hosted audio API/SDK | P2 |
| `gpustack` | yes | yes | Self-hosted OpenAI-compatible-ish | P2 |
| `localai` | yes | no | Self-hosted OpenAI-compatible-ish | P2 |
| `gitee_ai` | yes | yes | ASR compatible, TTS custom HTTP | P2 |
| `tencent` | yes | no | Dedicated ASR | Not first batch |
| `sambanova` | yes | no | ASR-only | Not first batch |
| `volcengine_maas` | yes | no | Dedicated ASR | Not first batch |
| `sagemaker` | yes | yes | Custom SageMaker endpoint | Not first batch |

The first implementation should embed only:

- OpenAI native audio.
- OpenAI-compatible audio.
- A provider registry that can later add Tongyi, MiniMax, FishAudio, and self-hosted adapters.

This gives broad coverage without introducing a plugin marketplace or many optional dependencies.

## Existing fast_agent Fit

Current relevant code shape:

- `agentclaw/model/manager.py`
  - `LLMConfig.model_type` currently documents `chat / embedding / rerank`, but `from_dict` already accepts arbitrary `model_type`.
  - `models.json` is already the central model configuration surface.
- `agentclaw/api/services/model_service.py`
  - `NON_CONVERSATION_MODEL_TYPES = {"embedding", "rerank"}` should later include `speech2text` and `tts`, so audio models do not appear in normal chat node model selection.
- `agentclaw/channels/__init__.py`
  - `ChannelMessage.message_type` already allows `audio`.
  - `attachments` can carry audio metadata or downloaded file references.
- `agentclaw/channels/wecom.py`
  - Current WeCom voice handling only reads platform-provided voice text content. Raw audio download and upload should be added later at the channel layer.
- `agentclaw/inputs/types.py`
  - `Audio` already exists as an input type marker.

## Architecture

Add a small audio model layer instead of expanding `LLMManager` with provider-specific audio logic.

Proposed location:

```text
agentclaw/audio/
  __init__.py
  types.py
  service.py
  providers/
    __init__.py
    base.py
    openai_audio.py
    registry.py
```

Responsibilities:

- `agentclaw/audio/types.py`
  - Define shared audio and voice data structures.
- `agentclaw/audio/providers/base.py`
  - Define provider protocols/interfaces.
- `agentclaw/audio/providers/openai_audio.py`
  - Implement OpenAI and OpenAI-compatible ASR/TTS.
- `agentclaw/audio/providers/registry.py`
  - Map `(channel/provider, model_type)` to an adapter.
- `agentclaw/audio/service.py`
  - Resolve default or explicit audio models from `LLMManager`.
  - Validate model type.
  - Dispatch to the provider adapter.
  - Provide `transcribe`, `synthesize`, and `list_voices`.

The audio service should depend on `LLMManager`/`LLMConfig`, but `LLMManager` should not grow large audio-provider branches.

## Data Types

```python
@dataclass
class AudioArtifact:
    data: bytes
    mime_type: str | None = None
    filename: str | None = None
    ext: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    duration_ms: int | None = None


@dataclass
class Voice:
    name: str
    value: str
    language: list[str] | None = None


@dataclass
class AudioStream:
    chunks: AsyncIterator[bytes]
    mime_type: str
    ext: str
```

`AudioArtifact` is the boundary between channel adapters and model providers. Channel adapters may fill only `data`, `mime_type`, and `filename` at first.

## Provider Interface

```python
class Speech2TextProvider(Protocol):
    async def transcribe(self, config: LLMConfig, audio: AudioArtifact) -> str:
        ...


class TTSProvider(Protocol):
    async def synthesize(
        self,
        config: LLMConfig,
        text: str,
        voice: str | None = None,
    ) -> AudioStream:
        ...

    async def voices(
        self,
        config: LLMConfig,
        language: str | None = None,
    ) -> list[Voice]:
        ...
```

The initial registry should be intentionally small:

```python
{
    ("openai", "speech2text"): OpenAIAudioProvider,
    ("openai", "tts"): OpenAIAudioProvider,
    ("openai_compatible", "speech2text"): OpenAICompatibleAudioProvider,
    ("openai_compatible", "tts"): OpenAICompatibleAudioProvider,
}
```

If the existing `channel` field is set to `openai` with `base_url`, it can use the same OpenAI-compatible code path.

## Model Configuration

Keep audio configuration in `models.json`.

Minimal shape:

```json
{
  "default": "qwen-chat",
  "speech2text": "openai-whisper",
  "tts": "openai-tts",
  "tts_voice": "alloy",
  "models": [
    {
      "id": "qwen-chat",
      "channel": "openai",
      "model_type": "chat",
      "model": "qwen-plus",
      "api_key": "${DASHSCOPE_API_KEY}",
      "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    },
    {
      "id": "openai-whisper",
      "channel": "openai",
      "model_type": "speech2text",
      "model": "whisper-1",
      "api_key": "${OPENAI_API_KEY}"
    },
    {
      "id": "openai-tts",
      "channel": "openai",
      "model_type": "tts",
      "model": "tts-1",
      "api_key": "${OPENAI_API_KEY}",
      "voice": "alloy",
      "audio_format": "mp3"
    }
  ]
}
```

OpenAI-compatible example:

```json
{
  "id": "compatible-asr",
  "channel": "openai_compatible",
  "model_type": "speech2text",
  "model": "whisper-large-v3",
  "api_key": "${COMPATIBLE_API_KEY}",
  "base_url": "https://example.com/v1"
}
```

Provider-specific optional fields should remain flat and minimal:

- `voice`: default voice for this TTS model.
- `audio_format`: default TTS output format, first batch defaults to `mp3`.
- `supported_file_extensions`: optional provider metadata.
- `file_upload_limit_mb`: optional provider metadata.

Do not add a plugin manifest format in the first version.

## Public API

Add audio APIs under the existing API layer. Proposed location:

```text
agentclaw/api/routers/admin/audio.py
agentclaw/api/schemas/audio.py
```

Register `audio.py` from `agentclaw/api/routers/admin/router.py`. With the existing admin router prefix, the first API surface should be `/admin/audio/...`. If public workflow execution also needs audio later, add a separate public router after the model layer is stable.

Initial endpoints:

```text
POST /admin/audio/speech-to-text
Content-Type: multipart/form-data

file: audio file
model_id?: string

Response:
{ "text": "..." }
```

```text
POST /admin/audio/text-to-speech
Content-Type: application/json

{
  "text": "hello",
  "voice": "alloy",
  "model_id": "openai-tts"
}

Response:
streaming audio bytes
Content-Type: audio/mpeg
```

```text
GET /admin/audio/voices?model_id=openai-tts&language=zh-Hans

Response:
[
  { "name": "Alloy", "value": "alloy", "language": ["zh-Hans", "en-US"] }
]
```

The public route, if added later, can mirror this contract under the existing public `/api` prefix.

## Channel Integration

Channel adapters should not know provider details.

Inbound audio flow:

```text
platform event
-> channel adapter downloads audio
-> AudioArtifact
-> AudioService.transcribe(...)
-> ChannelMessage.message becomes recognized text
-> workflow execution
```

Outbound TTS flow:

```text
workflow output text
-> channel config checks whether TTS is enabled
-> AudioService.synthesize(...)
-> channel adapter uploads/sends platform voice/audio message
```

Per-channel differences should live in channel config, for example:

```json
{
  "channel_audio": {
    "wecom": {
      "speech2text": "openai-whisper",
      "tts": "openai-tts",
      "tts_voice": "alloy",
      "tts_enabled": false
    },
    "feishu": {
      "speech2text": "openai-whisper",
      "tts": "openai-tts",
      "tts_voice": "nova",
      "tts_enabled": true
    }
  }
}
```

This is optional for the first model/API implementation. The first version can use global defaults from `models.json`.

## OpenAI First-Batch Behavior

ASR:

- Supported initial models: `whisper-1`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe`.
- Input: `AudioArtifact`.
- Adapter creates a file-like object with a useful name based on `filename`/`ext`, not always `temp.mp3`.
- Call OpenAI transcription API.
- Return `response.text`.

TTS:

- Supported initial models: `tts-1`, `tts-1-hd`, `gpt-4o-mini-tts`.
- Static default voice: `alloy`.
- Static voices: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `onyx`, `nova`, `sage`, `shimmer`, `verse`.
- Default output format: `mp3`.
- Return streaming chunks and `mime_type="audio/mpeg"`.

Do not implement long-text audio merging in the first batch. If text exceeds provider limits, return a clear validation error or let the provider error surface in a normalized form. Long-text splitting can be added later if needed.

## Error Handling

Keep first-batch errors simple:

- No configured model for `speech2text` or `tts`.
- Selected model has wrong `model_type`.
- Unsupported provider/model type combination.
- Empty audio input.
- Empty TTS text.
- Provider invocation failed.

Avoid speculative audio transcoding in the first version. If a platform gives a format the model does not support, channel code can either pass it through and let provider fail, or a later `AudioNormalizer` can transcode using a dedicated dependency.

## Testing Plan

Focused tests for first implementation:

- `LLMConfig` accepts `model_type="speech2text"` and `model_type="tts"`.
- `ModelService.list_available_models()` excludes `speech2text` and `tts`.
- `AudioService` resolves default `speech2text` and `tts` model ids from config.
- `AudioService.transcribe()` rejects wrong model type.
- `AudioService.synthesize()` uses model default `voice` when request voice is missing.
- OpenAI provider builds the transcription request with a file-like object preserving filename/extension.
- OpenAI provider returns voice list in `{name, value, language}` shape.
- API tests for:
  - multipart ASR returns `{text}`.
  - TTS returns streaming bytes with correct content type.
  - voices returns a list.

Provider API calls should be mocked in unit tests.

## Implementation Phases

### P0: Model and API Foundation

- Add audio data types and provider protocols.
- Add OpenAI/OpenAI-compatible provider.
- Add audio service.
- Extend `models.json` handling with `speech2text`, `tts`, and `tts_voice`.
- Exclude `speech2text` and `tts` from normal chat model selection.
- Add admin audio routes and schemas.
- Add focused tests.

### P1: Channel Integration

- Add inbound audio pipeline for channels that can download raw audio.
- Add optional outbound TTS per channel.
- Start with one channel after the API/model layer is stable, likely WeCom because existing voice handling already exists.

### P2: More Providers

- Add Tongyi when Chinese ASR/TTS is needed.
- Add MiniMax for dedicated TTS quality and voice inventory.
- Add FishAudio for reference voice/model based TTS.
- Add self-hosted adapters for Xinference/GPUStack/LocalAI if deployment needs them.

## Decisions

- Use `speech2text` and `tts` as first-class model types.
- Use `models.json` for default model and voice configuration.
- Add a small built-in provider registry, not a plugin marketplace.
- First embedded provider family is OpenAI/OpenAI-compatible.
- Channel adapters handle platform audio transport only.
- Audio service/provider layer handles model invocation only.
- Preserve real audio format metadata instead of assuming mp3.

## Open Questions

- Whether global `tts_voice` should remain top-level only or also be supported per TTS model. The recommended first version supports both, with per-model `voice` taking precedence.
- Which channel should be the first real inbound/outbound audio integration after the model/API foundation.
