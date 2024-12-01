"""Main entry point for Wyoming satellite."""
from pprint import pprint;

import argparse
import asyncio
import logging
import sys
import json

from functools import partial
from pathlib import Path
from wyoming.info import  AsrModel, AsrProgram, Attribution, Info
#from wyoming.info import Attribution, Info
#from .sonus import SonusProgram, SonusModel
from wyoming.server import AsyncServer

from .sonus_handler import SonusBase
from .event_handler import SonusEventHandler

logging.basicConfig(
            format='%(asctime)s %(levelname)-8s %(message)s',
            level=logging.DEBUG,
            datefmt='%Y-%m-%d %H:%M:%S'
            )

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
    #logging.basicConfig(level=logging.DEBUG)
    _LOGGER.debug("in main")
    reader, writer = await connect_stdin_stdout()
    _LOGGER.debug("after reader/writer")
    server: AsyncServer
    config_info = None
    """Main entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", help="URI for this Wyoming sonus service")
    # Sounds
    parser.add_argument(
        "--config", help="json file holding config parms"
    )

    parser.add_argument(
        "--incrementalTranscription", action="store_true", help="should this service support incremental speech transcription"
    )

    parser.add_argument("--debug", action="store_true", help="Log DEBUG messages")

    args = parser.parse_args()

    _LOGGER.info("testing")
    _LOGGER.debug(args)

    with open(args.config) as f:
        config_info = json.load(f)
    _LOGGER.debug(config_info)

    service = SonusBase(config_info,args,None, None)

    instance = asyncio.create_task(service.runit())    

    '''    
    wyoming_info = Info(
        asr=[
            SonusProgram(
                name="sonus handler",
                description="wyoming local app model",
                attribution=Attribution(
                    name="Sam Detweiler",
                    url="https://github.com/sdetweil/google-streaming-asr",
                ),
                installed=True,
                version="1.0.0",
                models=[
                    SonusModel(
                        name="sonus handler",
                        description="wyoming local app model",
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
    '''
    wyoming_info = Info(
        asr=[
            AsrProgram(
                name="google-streaming",
                description="google cloud streaming asr",
                attribution=Attribution(
                    name="Sam Detweiler",
                    url="https://github.com/sdetweil/wyominggoogle",
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
                        languages=""
                    )
                ]
            )
        ]
    )


    
    server = AsyncServer.from_uri(args.uri)
    _LOGGER.debug("setup AsyncServer %s",args.uri)

    #try:
    await server.run(        
        partial(
            SonusEventHandler, #sillyEventHandler,
            wyoming_info,
            service, 
            writer,
            args
        )
    )
    #except KeyboardInterrupt:
    #    _LOGGER.debug("ending")
    #    pass
    #finally:
    #    _LOGGER.debug("fribble")
    #    await service._stop()
    #    await instance

    _LOGGER("exiting")

# -----------------------------------------------------------------------------


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
