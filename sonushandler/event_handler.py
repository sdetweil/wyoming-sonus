"""Wyoming event handler for satellites."""
import argparse
import logging
import time

import asyncio
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
        sonus: SonusBase,
        writer: asyncio.StreamWriter,
        cli_args: argparse.Namespace,
        *args,
        **kwargs,
    ) -> None:
  
        super().__init__(*args, **kwargs)
        #print("in event init");
        self.cli_args = cli_args
        self.wyoming_info_event = wyoming_info.event()
        self.client_id = str(time.monotonic_ns())
        self.sonus = sonus
        self._writer = writer
        
        _LOGGER.info("client connected")
        self.sonus.startMicService()
        if self.sonus.server_id is None:
            # Take over after a problem occurred
            self.sonus.set_server(self.client_id, self.writer)

        elif self.sonus.server_id != self.client_id:
            # New connection
            _LOGGER.debug("Connection cancelled: %s", self.client_id)
    # ------------------------------------------------------------------------- 
    async def handle_event(self, event: Event) -> bool:
        """Handle events from the server."""
        _LOGGER.debug("in handle event")
        if Describe.is_type(event.type):
            _LOGGER.debug("in describe")
            await self.write_event(self.wyoming_info_event)            
            return True       
         
        _LOGGER.debug("received event type %s from app",event.type )
        await self.sonus.event_from_server(event)
        return True

    async def disconnect(self) -> None:
        """Server disconnect."""
        _LOGGER.debug("client disonnected")
        await self.sonus.stopMicService()
        if self.sonus.server_id == self.client_id:
            self.sonus.clear_server()
