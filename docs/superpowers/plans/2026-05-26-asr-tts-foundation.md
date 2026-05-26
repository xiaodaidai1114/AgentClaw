# ASR/TTS Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first ASR/TTS foundation: audio model types, OpenAI/OpenAI-compatible provider adapters, admin audio API, voice query, and focused tests.

**Architecture:** Add `agentclaw/audio` as a small model-provider layer that depends on `LLMConfig`/`LLMManager` but keeps audio-provider logic out of `LLMManager`. Expose admin endpoints under `/admin/audio/...`; channel adapters continue to only pass normalized audio artifacts later.

**Tech Stack:** Python 3, FastAPI, Pydantic, pytest, OpenAI Python SDK.

---

### Task 1: Audio Types and Provider Registry

**Files:**
- Create: `agentclaw/audio/types.py`
- Create: `agentclaw/audio/providers/base.py`
- Create: `agentclaw/audio/providers/registry.py`
- Create: `agentclaw/audio/providers/__init__.py`
- Create: `agentclaw/audio/__init__.py`
- Test: `agentclaw/test/unit/test_audio_service.py`

- [ ] Write failing tests for `AudioArtifact`, `AudioStream`, `Voice`, and provider registry lookup.
- [ ] Run: `pytest agentclaw/test/unit/test_audio_service.py -q`
- [ ] Implement the minimal audio types and registry.
- [ ] Run the same test and verify it passes.

### Task 2: OpenAI Audio Provider

**Files:**
- Create: `agentclaw/audio/providers/openai_audio.py`
- Modify: `agentclaw/audio/providers/registry.py`
- Test: `agentclaw/test/unit/test_audio_service.py`

- [ ] Write failing tests for OpenAI ASR file naming, TTS streaming metadata, default voices, and invalid voice fallback.
- [ ] Run: `pytest agentclaw/test/unit/test_audio_service.py -q`
- [ ] Implement `OpenAIAudioProvider` and register OpenAI/OpenAI-compatible keys.
- [ ] Run the same test and verify it passes.

### Task 3: Audio Service and Model Defaults

**Files:**
- Create: `agentclaw/audio/service.py`
- Modify: `agentclaw/model/manager.py`
- Modify: `agentclaw/api/services/model_service.py`
- Test: `agentclaw/test/unit/test_audio_service.py`

- [ ] Write failing tests for default `speech2text`/`tts` model resolution, wrong model type rejection, and exclusion from chat model selection.
- [ ] Run: `pytest agentclaw/test/unit/test_audio_service.py -q`
- [ ] Implement `AudioService`, `LLMManager` audio default properties, and non-conversation filtering.
- [ ] Run the same test and verify it passes.

### Task 4: Admin Audio API

**Files:**
- Create: `agentclaw/api/schemas/audio.py`
- Modify: `agentclaw/api/schemas/__init__.py`
- Create: `agentclaw/api/routers/admin/audio.py`
- Modify: `agentclaw/api/routers/admin/router.py`
- Test: `agentclaw/test/api/test_admin_audio_api.py`

- [ ] Write failing API tests for `/admin/audio/speech-to-text`, `/admin/audio/text-to-speech`, and `/admin/audio/voices`.
- [ ] Run: `pytest agentclaw/test/api/test_admin_audio_api.py -q`
- [ ] Implement schemas and router.
- [ ] Run the API test and verify it passes.

### Task 5: Verification

**Files:**
- All files above.

- [ ] Run focused tests:
  - `pytest agentclaw/test/unit/test_audio_service.py agentclaw/test/api/test_admin_audio_api.py -q`
- [ ] Run existing adjacent tests:
  - `pytest agentclaw/test/unit/test_llm_manager_reload.py agentclaw/test/api/test_management_api_contracts.py -q`
- [ ] Commit implementation.
