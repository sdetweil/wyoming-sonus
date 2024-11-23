"""Wyoming event handler for satellites."""
import argparse
import logging
import time

from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler

from .sonus_handler import SonusBase

_LOGGER = logging.getLogger()


class SonusEventHandler(AsyncEventHandler):
    """Event handler for clients."""

    def __init__(
        self,
        wyoming_info: Info,
        satellite: SonusBase,
        cli_args: argparse.Namespace,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        self.cli_args = cli_args
        self.wyoming_info_event = wyoming_info.event()
        self.client_id = str(time.monotonic_ns())
        self.satellite = satellite

    # -------------------------------------------------------------------------

    async def handle_event(self, event: Event) -> bool:
        """Handle events from the server."""
        if Describe.is_type(event.type):
            await self.write_event(self.wyoming_info_event)
            return True

        if self.satellite.server_id is None:
            # Take over after a problem occurred
            self.satellite.set_server(self.client_id, self.writer)
        elif self.satellite.server_id != self.client_id:
            # New connection
            _LOGGER.debug("Connection cancelled: %s", self.client_id)
            return False

        _LOGGER.debug("received event type %s from app",event.type )
        await self.satellite.event_from_server(event)

        return True

    async def disconnect(self) -> None:
        """Server disconnect."""
        if self.satellite.server_id == self.client_id:
            self.satellite.clear_server()
