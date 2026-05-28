"""
Audio API schemas.
"""

from typing import Optional

from pydantic import BaseModel


class SpeechToTextResponse(BaseModel):
    text: str


class TextToSpeechRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    model_id: Optional[str] = None


class VoiceInfo(BaseModel):
    name: str
    value: str
    language: Optional[list[str]] = None
