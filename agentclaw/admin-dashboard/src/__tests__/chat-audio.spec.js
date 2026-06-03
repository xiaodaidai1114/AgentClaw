import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('admin chat audio integration', () => {
  it('exposes admin audio API wrappers', () => {
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')

    expect(apiSource).toContain('export const audioApi')
    expect(apiSource).toContain("speechToText")
    expect(apiSource).toContain("textToSpeech")
    expect(apiSource).toContain("voices")
    expect(apiSource).toContain("responseType: 'blob'")
    expect(apiSource).toContain("'/audio/speech-to-text'")
    expect(apiSource).toContain("'/audio/text-to-speech'")
  })

  it('exposes public audio API wrappers without admin authentication', () => {
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')

    expect(apiSource).toContain('export const publicAudioApi')
    expect(apiSource).toContain('publicSessionHeaders')
    expect(apiSource).toContain("`/public/workflows/${encodeURIComponent(workflowId)}/speech-to-text`")
    expect(apiSource).toContain("`/public/workflows/${encodeURIComponent(workflowId)}/text-to-speech`")
    expect(apiSource).toContain("roomSpeechToText")
    expect(apiSource).toContain("roomTextToSpeech")
    expect(apiSource).toContain("`/public/rooms/${encodeURIComponent(roomId)}/speech-to-text`")
    expect(apiSource).toContain("`/public/rooms/${encodeURIComponent(roomId)}/text-to-speech`")
    expect(apiSource).toContain('withCredentials: true')
  })

  it('parses JSON error payloads returned as blobs from public audio calls', () => {
    const apiSource = readFileSync(resolve(process.cwd(), 'src/api/index.js'), 'utf8')

    expect(apiSource).toContain('parseBlobJsonError')
    expect(apiSource).toContain("error.response?.data instanceof Blob")
    expect(apiSource).toContain("content-type")
    expect(apiSource).toContain("application/json")
    expect(apiSource).toContain("JSON.parse(await error.response.data.text())")
  })

  it('adds a speech input button to ChatInput', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatInput.vue'), 'utf8')

    expect(source).toContain('speechInputAvailable')
    expect(source).toContain('recording')
    expect(source).toContain("speech-input")
    expect(source).toContain("$emit('speech-input')")
    expect(source).toContain('chatInput.startSpeechInput')
    expect(source).toContain('chatInput.stopSpeechInput')
  })

  it('records browser audio and sends it to ASR from AgentChat', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain('audioApi')
    expect(source).toContain('navigator.mediaDevices.getUserMedia')
    expect(source).toContain('MediaRecorder')
    expect(source).toContain('startSpeechInput')
    expect(source).toContain('stopSpeechInput')
    expect(source).toContain('audioApi.speechToText')
    expect(source).toContain('publicAudioApi.speechToText')
    expect(source).toContain('speechInputAvailable')
    expect(source).toContain('workflow.chat_audio')
  })

  it('plays assistant messages with TTS on explicit click', () => {
    const messageSource = readFileSync(resolve(process.cwd(), 'src/components/chat/ChatMessage.vue'), 'utf8')
    const chatSource = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(messageSource).toContain('ttsAvailable')
    expect(messageSource).toContain('ttsState')
    expect(messageSource).toContain("$emit('speak')")
    expect(messageSource).toContain('chatMessage.speak')
    expect(messageSource).toContain('chatMessage.generatingSpeech')
    expect(messageSource).toContain('chatMessage.stopSpeech')
    expect(chatSource).toContain('@speak="speakMessage(msg)"')
    expect(chatSource).toContain('ttsMessageKey')
    expect(chatSource).toContain('ttsGenerating')
    expect(chatSource).toContain('ttsPlaying')
    expect(chatSource).toContain('messageAudioKey(msg)')
    expect(chatSource).toContain('audioApi.textToSpeech')
    expect(chatSource).toContain('publicAudioApi.textToSpeech')
    expect(chatSource).toContain('URL.createObjectURL')
    expect(chatSource).toContain('ttsPlaybackUrl')
  })

  it('uses room-scoped public audio endpoints in public room mode', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(source).toContain('if (this.isPublicRoomMode) return publicAudioApi.roomSpeechToText(this.publicRoomId, file)')
    expect(source).toContain('if (this.isPublicRoomMode) return publicAudioApi.roomTextToSpeech(this.publicRoomId, { text })')
  })

  it('allows public chat audio controls when workflow metadata enables them', () => {
    const chatSource = readFileSync(resolve(process.cwd(), 'src/views/AgentChat.vue'), 'utf8')

    expect(chatSource).toContain('return this.normalizedChatAudio.enabled && this.normalizedChatAudio.speech_input_enabled')
    expect(chatSource).toContain('return this.normalizedChatAudio.enabled && this.normalizedChatAudio.tts_enabled')
  })
})
