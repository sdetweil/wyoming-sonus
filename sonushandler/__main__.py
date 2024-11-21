"""Main entry point for Wyoming satellite."""
from pprint import pprint;

import argparse
import asyncio
import logging
import sys
import json

#from functools import partial
from pathlib import Path
#from wyoming.info import  AsrModel, AsrProgram, Attribution, Info
#from wyoming.info import Attribution, Info
#from wyoming.server import AsyncServer, AsyncTcpServer

from .event_handler import SonusEventHandler

_LOGGER = logging.getLogger()
_DIR = Path(__file__).parent

async def connect_stdin_stdout():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    w_transport, w_protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)
    return reader, writer


async def main() -> None:
    reader, writer = await connect_stdin_stdout()
    config_info = None
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket_address", help="url to socket server")
    # Sounds
    parser.add_argument(
        "--config", help="json file holding config parms"
    )

    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    _LOGGER.debug("socket_address=%s",args.socket_address)
    if args.socket_address is None:
        args.socket_address="http://localhost:8080"

    _LOGGER.info("testing")
    _LOGGER.debug(args)

    with open(args.config) as f:
        config_info = json.load(f)
    _LOGGER.debug(config_info)

    instance = asyncio.create_task(SonusEventHandler(config_info,args,None, None).runit())    
    await instance

    '''
    wyoming_info = Info(
        asr=[
            AsrProgram(
                name="google-streaming",
                description="google cloud streaming asr",
                attribution=Attribution(
                    name="Sam Detweiler",
                    url="https://github.com/sdetweil/google-streaming-asr",
                ),
                installed=True,
                version="1.0.0",
                models=[
                    AsrModel(
                        name="google-streaming",
                        description="google cloud streaming asr",
                        attribution=Attribution(
                            name="rhasspy",
                            url="https://github.com/rhasspy/models/",
                        ),
                        version="1.0.0",
                        installed=True,
                        languages="none",
                    )
                ]                
            )
        ]
    )
    
    server = AsyncServer
    if not server:
        _LOGGER.debug("server didn't start")
    _LOGGER.debug(wyoming_info)
    #model_lock = asyncio.Lock()
    _LOGGER.debug("calling server")
    await server.run(        
        partial(
            SonusEventHandler,
            wyoming_info,
            args,
            0,
            None #model_lock
        )
    )
    '''
    #_LOGGER("exiting")

# -----------------------------------------------------------------------------


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
