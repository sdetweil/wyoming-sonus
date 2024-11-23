
"""Speech to text."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from wyoming.event import Event, Eventable
from wyoming.info import Artifact

DOMAIN = "sonus"
_HOTWORD_TYPE = "hotword"
_COMMAND_TYPE = "command"

@dataclass
class Hotword(Eventable):
    """Transcription response from ASR system"""

    @staticmethod
    def is_type(event_type: str) -> bool:
        return event_type == _HOTWORD_TYPE

    def event(self) -> Event:

        return Event(type=_HOTWORD_TYPE, data=None)

    @staticmethod
    def from_event(event: Event) -> "Hotword":
        assert event.data is not None
        return Hotword(text="hotword")


@dataclass
class Command(Eventable):
    """Command text.

    """

    text: Optional[str] = None
    """Name of Command model to use"""

    @staticmethod
    def is_type(event_type: str) -> bool:
        return event_type == _COMMAND_TYPE

    def event(self) -> Event:
        data: Dict[str, Any] = {}
        if self.text is not None:
            data["text"] = self.text

        return Event(type=_COMMAND_TYPE, data=data)

    @staticmethod
    def from_event(event: Event) -> "Command":
        data = event.data or {}
        return Command(text=data.get("text"))
    
@dataclass
class SonusModel(Artifact):
    """Speech-to-text model."""

    languages: list[str]
    """List of supported model languages."""


@dataclass
class SonusProgram(Artifact):
    """Speech-to-text service."""

    models: list[SonusModel]
    """List of available models."""
