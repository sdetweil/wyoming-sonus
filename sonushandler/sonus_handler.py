"""Wyoming event handler for satellites."""
from pprint import pprint;
import argparse
import asyncio
import sys
import logging
import time
import math
from array import array
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Union
import json
from pyring_buffer import RingBuffer
from queue import Queue
from wyoming.event import Event
from wyoming.info import Describe, Info
from wyoming.server import AsyncEventHandler
from .sonus  import Hotword, Command

#from wyoming.asr import  Transcribe
from .xasr import xTranscript, xTranscribe
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient, AsyncTcpClient
from wyoming.error import Error
from wyoming.event import Event, async_write_event
from wyoming.tts import Synthesize, SynthesizeVoice
from wyoming.snd import Played

from wyoming.vad import VoiceStarted, VoiceStopped 
from wyoming.wake import Detect, Detection, NotDetected


from .vad import SileroVad

_LOGGER = logging.getLogger()

class State(Enum):
    IDLE = auto()                   # doing nothing
    LISTENING = auto()              # listening for hotword
    PROCESSING_FOR_TEXT = auto()    # looking for text content
    SPEAKING = auto()               # audio out
    WAITING = auto()                # waiting for asr to reply

class PrintRequest:
    def __init__(self, d):
       for key in d.keys():
            self.__setattr__(key, d[key])
    client: str;
    data: str;

class InfoRequest:
    option: int
    text :str 

class SonusBase:
    """Event handler for clients."""

    def __init__(
        self,       
        config_info,   
        cli_args: argparse.Namespace,
        *args,
        **kwargs,
    ) -> None:
        super().__init__() # *args, **kwargs)
    
        self.cli_args = cli_args     
        self.config_info =config_info
        #self.stdout_writer = stdout_writer
        #self.wyoming_info_event = wyoming_info.event()
        self._writer: Optional[asyncio.StreamWriter] = None 
        self._mic_task: Optional[asyncio.Task] = None
        self._mic_webrtc: Optional[Callable[[bytes], bytes]] = None
        self._wake_task: Optional[asyncio.Task] = None
        self._wake_queue: "Optional[asyncio.Queue[Event]]" = None        
        self.WW_timeout_task:  Optional[asyncio.Task] = None
        self._snd_task: Optional[asyncio.Task] = None
        self._snd_queue: "Optional[asyncio.Queue[Event]]" = None
        self._asr_task: Optional[asyncio.Task] = None
        self._asr_queue: "Optional[asyncio.Queue[Event]]" = None   
        self.reco_timeout_task: Optional[asyncio.Task] = None
        self._tts_task: Optional[asyncio.Task] = None
        self._tts_queue: "Optional[asyncio.Queue[Event]]" = None  
        self.speakQueue: "Optional[asyncio.Queue[PrintRequest]]" = None 
        self._sendQueue:  "Optional[asyncio.Queue[InfoRequest]]" = None
        self.client_id = str(time.monotonic_ns())
        self.state:State = State.IDLE
        self.is_running:bool = False
        self.mic_is_running: bool = False
        self.is_streaming:bool = False
        self.buffered_event: Event = None
        self.transcript:str = ""
        self.speaking :bool = False 
        self.server_id: Optional[str] = None
        if self.config_info['speaking'] == 1:
            self.speaking = True
        self.connectedClients = []
        self.vad = SileroVad(
            threshold=self.config_info['vad']['threshold'], trigger_level=self.config_info['vad']['trigger_level']
        )

        # Timestamp in the future when we will have timed out (set with
        # time.monotonic())
        #self.timeout_seconds: Optional[float] = None

        # Audio from right before speech starts (circular buffer)
        self.vad_buffer: Optional[RingBuffer] = None

        _LOGGER.debug("done w init")

    def set_server(self, server_id: str, writer: asyncio.StreamWriter) -> None:
        """Set event writer."""
        self.server_id = server_id
        self._writer = writer
        _LOGGER.debug("Server set: %s", server_id)

    def clear_server(self) -> None:
        """Remove writer."""
        self.server_id = None
        self._writer = None
        _LOGGER.debug("Server disconnected")
    
    async def handle_event(self, event: Event) -> bool:
        #_LOGGER.debug("received event")

        '''
            AudioChunk is the primary event type, from microphone, Synthesize text to speech
                                                  to wakeword, speech to text Transcribe, and sound out 
                it is positioned first as its more frequent                                                  
        '''        
        if AudioChunk.is_type(event.type):
            # if we are idle 
            if self.state is State.IDLE :
                # if not silence
                if await self.isSilence(event) is False:
                    if self.is_streaming is False:
                        self.is_streaming = True
                        # set state to listening for hotword
                        self.state = State.LISTENING
                        #_LOGGER.debug("setting listening state. sending wake_detect to wakeword")
                        await self._send_wake_detect()
                        '''
                        if not self.buffered_event == None:
                            _LOGGER.debug("sending VAD buffered event on to wakeword")
                            await self.forwardEvent(self.buffered_event, self._wake_queue)
                            self.buffered_event = None
                        else: 
                        '''
                        _LOGGER.debug("sending event on to wakeword")
                        await self.forwardEvent(event, self._wake_queue)  
                        
                        #asyncio.create_task(self.setTimeout(self.WW_timeout_task, self.config_info["wake"]["wake_word_timeout"],self._wake_queue, "wakeword timeout" ))
                    else:
                        return False                        
                else:
                    if self.state is State.PROCESSING_FOR_TEXT:
                        self.state = State.IDLE
                    return False;         

            elif self.state == State.LISTENING:    
                # if listening for hotword, send to hotword handler
                if await self.isSilence(event) is False:
                    #_LOGGER.debug("in listening state. sending Chunk to wakeword")
                    await self.forwardEvent(event, self._wake_queue) 
                else:    
                    _LOGGER.debug("listening for wakeword, but heard silence.. start over")
                    await  self.sendEvent(AudioStop().event(), self._wake_queue)
                    self.state = State.IDLE

            elif self.state in (State.PROCESSING_FOR_TEXT , State.SPEAKING) :
                # if processing speech to text
                if self.state == State.PROCESSING_FOR_TEXT:
                   if await self.isSilence(event) is False:      
                        _LOGGER.debug("sending chunk for speech reco")                 
                        await self.forwardEvent(event, self._asr_queue) 
                        if  self.reco_timeout_task is not None:
                            self.reco_timeout_task.cancel()
                            await self.setTimeout(self.reco_timeout_task, self.config_info["stt"]["transcript_timeout"],self._asr_queue, "transcript timeout" )                      
                   else:
                        _LOGGER.debug("was processing for text, now silence, trigger text")
                        self.state = State.WAITING                         
                        if  self.reco_timeout_task is not None:
                            self.reco_timeout_task.cancel()
                            self.reco_timeout_task= None    
                            await self.clearQueue(self._wake_queue)   
                        await self.sendEvent(AudioStop().event(), self._asr_queue)                                                                
                else:     
                    _LOGGER.debug("sending audio chunk to sound service")
                    await self.forwardEvent(event, self._snd_queue)                      

            elif self.state is State.WAITING:  
                # waiting for the Transcription, toss all input  
                _LOGGER.debug("waiting for transcription or something")
            
        #
        #   this is Hotword detection
        #            
        elif Detection.is_type(event.type):
            _LOGGER.debug("received hotword detection event")            
            self.state = State.PROCESSING_FOR_TEXT
            # start transcription
            _LOGGER.debug("change state to Transcribing")
            print("===>hotword<===")
            await self.notifyManager(1, "hotword", False)
            sys.stdout.flush()            
            await self.sendEvent(xTranscribe(sendPartials=True).event(), self._asr_queue)   
            await self.setTimeout(self.reco_timeout_task, self.config_info["stt"]["transcript_timeout"],self._asr_queue, "transcript timeout" )

        #
        #   this is Hotword  NOT detected.. timed out 
        #        
        elif NotDetected.is_type(event.type):
            _LOGGER.debug("wake word said heard not wakeword")
            self.state = State.IDLE
        
        #
        #   this is the Speech to text , text output
        #        
        elif xTranscript.is_type(event.type):
            # heard from ASR with text string
            # echo out to surrounding process via stdout
            # set back to idle state
            if  self.reco_timeout_task is not None:
                self.reco_timeout_task.cancel()
                self.reco_timeout_task= None

            transcript=event.data["text"];    
            print("===>"+transcript+"<===")
            
            sys.stdout.flush()       
            if "is_final" in event.data and event.data["is_final"] is False :
                _LOGGER.debug("more transcript to come")
                await self.notifyManager(2, transcript, False)
            else:    
                await self.notifyManager(2, transcript, True)
                self.state = State.IDLE               
                _LOGGER.debug("transcript response received ==>%s<==", transcript)
                if self.speaking:
                    self.state = State.WAITING
                    _LOGGER.debug("sending Synthesize event")
                    await self.sendEvent(Synthesize(text=transcript).event(), self._tts_queue)               

        
        #         
        #    elif SpeakText.is_type(event.type):
        #        sendEvent(AudioStart.event(), Speaker.Handler)
        #        self.State=State.SPEAKING
        #            


        #
        #   this is Auudio Start output of the Text to Speech
        #      we will just forward this to the sound out service
        #
        elif AudioStart.is_type(event.type) :
            _LOGGER.debug("received AudioStart event")
            if self.state == State.IDLE:
                _LOGGER.debug("in idle state")
                return True
            else:    
                # audio back from TTS service
                self.state = State.SPEAKING
                await self.forwardEvent(event, self._snd_queue) 
        
        elif AudioStop.is_type(event.type) :
            _LOGGER.debug("received AudioStop event")
            # no more audio from TTS service
            if self.state is State.SPEAKING:
                await self.forwardEvent(event, self._snd_queue) 
                #self.state = State.IDLE     

        elif Played.is_type(event.type) :
            _LOGGER.debug("received Played event")
            #if self.state is State.SPEAKING:
            self.state = State.IDLE   

        else:
            _LOGGER.debug("unexpected event received =%s",event.type)
        return True    
    
    async def setTimeout(self,task, timeout, queue, message):
        try: 
            async with asyncio.timeout(timeout):                
                task= asyncio.create_task(self.sleeproutine(timeout+1)) # force longer than 
            await task
                                
        except TimeoutError:                
                self.state=State.LISTENING
                task=None
                _LOGGER.debug(message)
                await self.sendEvent(AudioStop().event(), queue)

    async def event_from_server(self, event: Event) -> None:
        await self.handle_event(event)

    async def event_to_server(self, event: Event) -> None:
        """Send an event to the server."""
        if self._writer is None:
            return

        try:
            await async_write_event(event, self._writer)
        except Exception as err:
            self.clear_server()

            if isinstance(err, ConnectionResetError):
                _LOGGER.warning("Server disconnected unexpectedly")
            else:
                _LOGGER.exception("Unexpected error sending event to server")

    async def runit(self) -> None:
        await self.setup()           
        _LOGGER.debug("awaiting started")
        await self.started()

    async def setup(self) -> None:
        self.is_running = True
        # 
        # is vad buffer size defined, create it now
        #
        if self.config_info['vad']['buffer_seconds'] > 0:
            # Assume 16Khz, 16-bit mono samples
            vad_buffer_bytes = int(math.ceil(self.config_info['vad']['buffer_seconds'] * 16000 * 2))
            self.vad_buffer = RingBuffer(maxlen=vad_buffer_bytes)        
        self._sendQueue= asyncio.Queue()              
        self.speakQueue = asyncio.Queue()        
        self._connect_to_services(self.config_info)                  

    async def _stop(self) -> None:
        """Disconnect from services."""
        self.server_id = None
        self._writer = None

        await self._disconnect_from_services()
        self.state = State.STOPPED

    async def stopped(self) -> None:
        """Called when satellite has stopped."""

    async def stopMicService(self)-> None:    
        if self._mic_task is not None:
            try:
                self.mic_is_running = False
                self._mic_task.cancel()
                self._mic_task = None
            except:
                pass    

    def startMicService(self)->None:
        if not self.config_info['mic_address'].endswith(":0"):
            self.mic_is_running = True
            _LOGGER.debug(
                "Connecting to mic service: %s",
                self.config_info['mic_address'],
            )
            self._mic_task = asyncio.create_task(self._mic_task_proc(self.config_info['mic_address']), name="mic")          

    async def started(self) -> None:
        """Called when satellite has started."""
       
        while  True:
            await asyncio.sleep(24*60*60*1000)                 

    '''
        use socket io to notify outside app 
    '''
    async def notifyManager(self,type:int,text:str, is_final:bool)->None:
        if self._writer is not None:
            event:Event =None
            if type == 1:
                event=Hotword().event() 
            else:            
                event=Command(text, is_final).event()   
            _LOGGER.debug("sending event type=%s to access point", event.type)                                   
            await self.event_to_server(event) 
        else:
            _LOGGER.debug("no service manager connected")            
    
    '''
        dummy routine to use for timeout handling
        this routine should never actually DO anything other than sleep
    '''    
    
    async def sleeproutine(self, time) -> None:
        try:
            await asyncio.sleep(time)
        except asyncio.CancelledError:
            _LOGGER.debug("sleep asyncio canceled error")

    '''
        check the current buffer stream for silence
        it is possible that we need multiple buffers to tell
        and need to send those if NOT silence
    '''

    async def isSilence(self,event) -> bool:
        # Only unpack chunk once
        chunk: Optional[AudioChunk] = None
        audio_bytes: bytes = None
        '''
        if (
            self.is_streaming
            and (self.timeout_seconds is not None)
            and (time.monotonic() >= self.timeout_seconds)
        ):
            # Time out during wake word recognition
            self.is_streaming = False
            self.timeout_seconds = None
            #await self.sendEvent(AudioStop().event(), self._wake_queue)
            #return True
        '''    
        
        # not timeout 
        if not self.is_streaming:
            # Check VAD
            if audio_bytes is None:
                if chunk is None:
                    # Need to unpack
                    chunk = AudioChunk.from_event(event)

                audio_bytes = chunk.audio

            if not self.vad(audio_bytes):
                # No speech
                #_LOGGER.debug("silence")
                if self.vad_buffer is not None:
                    self.vad_buffer.put(audio_bytes)
                return True
            
            _LOGGER.debug("NOT silence")
            '''
            if self.config_info['wake']['wake_word_timeout'] is not None:
                # Set future time when we'll stop streaming if the wake word
                # hasn't been detected.
                self.timeout_seconds = (
                    time.monotonic() + self.config_info['wake']['wake_word_timeout']
                )
            else:
                # No timeout
                self.timeout_seconds = None
            '''    

            if self.vad_buffer is not None:
                # Send contents of VAD buffer first. This is the audio that was
                # recorded right before speech was detected.
                if chunk is None:
                    chunk = AudioChunk.from_event(event)
                    audio_bytes = chunk.audio
                    
                self.vad_buffer.put(audio_bytes)
                    
                # send the prior saved buffer
                self.buffered_event= AudioChunk(
                        rate=chunk.rate,
                        width=chunk.width,
                        channels=chunk.channels,
                        audio=self.vad_buffer.getvalue(),
                    ).event()

            self._reset_vad()
        return False
    
    '''
        clear a queue of all events(if any)
    '''
    
    async def clearQueue(self, que:Queue) -> None:
        while not que.empty:
            que.get()

    def _reset_vad(self):
        """Reset state of VAD."""
        self.vad(None)

        if self.vad_buffer is not None:
            # Clear buffer
            self.vad_buffer.put(bytes(self.vad_buffer.maxlen))
    
    '''
        send an event to a particular service queue, created in this app
    '''

    async def sendEvent(self, event, destination:asyncio.Queue) -> None:
        if destination != None:
            if event != None:
                destination.put_nowait(event)
            else:
                _LOGGER.debug("no event found in send Event")    
        else:
            _LOGGER.debug("no send destination for event")            
        return True
    
    '''
        forward an event to a particular service queue, from some other service
    '''

    async def forwardEvent(self, event:Event, destination:asyncio.Queue) -> None:      
        if destination != None:
            destination.put_nowait(event)
        else:
            _LOGGER.debug("no forward destination for event")

        return True 
    
    async def speakQueueHandler(self):
        while self.is_running:
            try:
                msg:PrintRequest= self.speakQueue.get(0)
                await self.sendEvent(Synthesize(text=msg.data).event(),self._tts_queue)
            except:
                _LOGGER.debug("exception in handling print request")

    '''
        connect to the configured (config.json) services
            microphone
            wakeword
            speech to text
            text to speech
            sound
    '''
    def _connect_to_services(self, config_info) -> None:
        """Connects to configured services."""
        _LOGGER.debug("entered _connect_to_services")
        if config_info['snd']['enabled'] == 1 :
            self._snd_task = asyncio.create_task(self._snd_task_proc(config_info['snd_address']), name="snd")

        if not config_info['wake_address'].endswith(":0"):
            _LOGGER.debug(
                "Connecting to wake service: %s",
                config_info['wake_address'],
            )
            self._wake_task = asyncio.create_task(self._wake_task_proc(config_info['wake_address']), name="wake")


        if not config_info['asr_address'].endswith(":0"):
            _LOGGER.debug(
                "Connecting to asr service: %s",
                config_info['asr_address'],
            )
            self._asr_task = asyncio.create_task(self._asr_task_proc(config_info['asr_address']), name="event"
            )

        if not config_info['tts_address'].endswith(":0"):
            _LOGGER.debug(
                "Connecting to tts service: %s",
                config_info['tts_address'],
            )
            self._tts_task = asyncio.create_task(self._tts_task_proc(config_info['tts_address']), name="event"
            )            
        #
        # enable mic last as it is streaming packets all the time
        #             
        if 0 == 1:
            if not config_info['mic_address'].endswith(":0"):
                _LOGGER.debug(
                    "Connecting to mic service: %s",
                    config_info['mic_address'],
                )
                self._mic_task = asyncio.create_task(self._mic_task_proc(config_info['mic_address']), name="mic")            

        _LOGGER.info("Connected to services")

    '''
        this is the processing task for speech to text
    '''
    async def _asr_task_proc(self, address) -> None:
        """Speech Reco service loop."""
        asr_client: Optional[AsyncClient] = None
        audio_bytes: Optional[bytes] = None
        to_service_task: Optional[asyncio.Task] = None
        from_service_task: Optional[asyncio.Task] = None
        pending: Set[asyncio.Task] = set()

        async def _disconnect() -> None:
            nonlocal to_service_task, from_service_task
            try:
                if asr_client is not None:
                    await asr_client.disconnect()

                # Clean up tasks
                if to_service_task is not None:
                    to_service_task.cancel()
                    to_service_task = None

                if from_service_task is not None:
                    from_service_task.cancel()
                    from_service_task = None
            except Exception:
                pass  # ignore disconnect errors        

        while self.is_running:
            try:
                if self._asr_queue is None:
                    self._asr_queue = asyncio.Queue()

                if asr_client is None:
                    asr_client = AsyncClient.from_uri("tcp://"+address)
                    assert asr_client is not None
                    try:
                        await asr_client.connect()
                        _LOGGER.debug("Connected to asr service")
                    except:
                        _LOGGER.debug("asr connect failed")
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        asr_client = None
                        continue                          

                    # Reset
                    from_service_task = None
                    to_service_task = None
                    pending = set()
                    self._asr_queue = asyncio.Queue()

                # Read/write in "parallel"
                if to_service_task is None:
                    # From satellite to wake service
                    to_service_task = asyncio.create_task(
                        self._asr_queue.get(), name="to_asr_service"
                    )
                    pending.add(to_service_task)

                if from_service_task is None:
                    # From wake service to satellite
                    from_service_task = asyncio.create_task(
                        asr_client.read_event(), name="from_asr_service"
                    )
                    pending.add(from_service_task)

                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                if to_service_task in done:
                    # Event to go to asr service (speech reco)
                    _LOGGER.debug("in asr to service")
                    assert to_service_task is not None
                    event = to_service_task.result()
                    to_service_task = None
                    _LOGGER.debug("asr event out = %s",event.type)
                    await asr_client.write_event(event)

                if from_service_task in done:
                    # Event from asr service (detection)
                    _LOGGER.debug("in asr from service")                    
                    assert from_service_task is not None
                    event = from_service_task.result()
                    _LOGGER.debug("asr event in = %s",event.type)
                    from_service_task = None

                    if event is None:
                        _LOGGER.warning("asr service disconnected")
                        await _disconnect()
                        asr_client = None  # reconnect
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        continue

                    _LOGGER.debug("sending received Transcipt event on to mainline")
                    await self.handle_event(event)
            except asyncio.CancelledError:
                _LOGGER.debug("asr asyncio canceled error")
                break
            except Exception:
                _LOGGER.exception("Unexpected error in asr read task")
                await _disconnect()
                asr_client = None  # reconnect
                await asyncio.sleep(self.config_info["service_reconnect_seconds"])

        await _disconnect()        

    '''
        this is the processing task for text to speech
    '''

    async def _tts_task_proc(self, address) -> None:
        """text to speech service loop."""
        tts_client: Optional[AsyncClient] = None
        audio_bytes: Optional[bytes] = None
        to_service_task: Optional[asyncio.Task] = None
        from_service_task: Optional[asyncio.Task] = None
        pending: Set[asyncio.Task] = set()

        async def _disconnect() -> None:
            nonlocal to_service_task, from_service_task
            try:
                if tts_client is not None:
                    await tts_client.disconnect()

                # Clean up tasks
                if to_service_task is not None:
                    to_service_task.cancel()
                    to_service_task = None

                if from_service_task is not None:
                    from_service_task.cancel()
                    from_service_task = None
            except Exception:
                pass  # ignore disconnect errors        

        while self.is_running:
            try:
                if self._tts_queue is None:
                    self._tts_queue = asyncio.Queue()

                if tts_client is None:
                    tts_client = AsyncClient.from_uri("tcp://"+address)
                    assert tts_client is not None
                    try:
                        await tts_client.connect()
                        _LOGGER.debug("Connected to tts service")
                    except:
                        _LOGGER.debug("tts connect failed, wait retry")
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        tts_client = None
                        continue   

                    # Reset
                    from_service_task = None
                    to_service_task = None
                    pending = set()
                    self._tts_queue = asyncio.Queue()

                # Read/write in "parallel"
                if to_service_task is None:
                    # From satellite to wake service
                    to_service_task = asyncio.create_task(
                        self._tts_queue.get(), name="to_tts_service"
                    )
                    pending.add(to_service_task)

                if from_service_task is None:
                    # From wake service to satellite
                    from_service_task = asyncio.create_task(
                        tts_client.read_event(), name="from_tts_service"
                    )
                    pending.add(from_service_task)

                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                if to_service_task in done:
                    # Event to go to tts service (speech reco)
                    _LOGGER.debug("in tts to service")
                    assert to_service_task is not None
                    event = to_service_task.result()
                    to_service_task = None
                    _LOGGER.debug("tts event out = %s",event.type)
                    await tts_client.write_event(event)

                if from_service_task in done:
                    # Event from tts service (detection)
                    _LOGGER.debug("in tts from service")                    
                    assert from_service_task is not None
                    event = from_service_task.result()
                    _LOGGER.debug("tts event in = %s",event.type)
                    from_service_task = None

                    if event is None:
                        _LOGGER.warning("tts service disconnected")
                        await _disconnect()
                        tts_client = None  # reconnect
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        continue

                    _LOGGER.debug("sending received TTS event on to mainline")
                    await self.handle_event(event)
            except asyncio.CancelledError:
                _LOGGER.debug("tts asyncio canceled error")
                break
            except Exception:
                _LOGGER.exception("Unexpected error in mic read task")
                await _disconnect()
                tts_client = None  # reconnect
                await asyncio.sleep(self.config_info["service_reconnect_seconds"])

        await _disconnect() 

    '''
        this is the processing task for microphone input
    '''
    async def _mic_task_proc(self, address) -> None:
        """Mic service loop."""
        mic_client: Optional[AsyncClient] = None
        audio_bytes: Optional[bytes] = None

        '''if self.config_info["mic"]["needs_webrtc"] and (self._mic_webrtc is None):
            _LOGGER.debug("Using webrtc audio enhancements")
            self._mic_webrtc = WebRtcAudio(
                self.config_info["mic"]["auto_gain"], self.config_info["mic"]["noise_suppression"]
            )
        '''
        async def _disconnect() -> None:
            try:
                if mic_client is not None:
                    await mic_client.disconnect()
            except Exception:
                pass  # ignore disconnect errors

        while self.mic_is_running:
            try:
                if mic_client is None:
                    mic_client = AsyncClient.from_uri("tcp://"+address)
                    assert mic_client is not None
                    try:
                        await mic_client.connect()
                        _LOGGER.debug("Connected to mic service")
                    except:
                        _LOGGER.debug("mic connect failed, wait retry")
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        mic_client = None
                        continue   

                #_LOGGER.debug("reading from mic")
                try:
                    event = await mic_client.read_event()
                except: 
                    event=None
                    pass    
                if event is None:
                    _LOGGER.warning("Mic service disconnected")
                    await _disconnect()
                    mic_client = None  # reconnect
                    await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                    continue

                # Audio processing
                '''if self.config_info["mic"]["needs_processing"] and AudioChunk.is_type(
                    event.type
                ):
                    chunk = AudioChunk.from_event(event)
                    audio_bytes = self._process_mic_audio(chunk.audio)
                    event = AudioChunk(
                        rate=chunk.rate,
                        width=chunk.width,
                        channels=chunk.channels,
                        audio=audio_bytes,
                    ).event()
                else:
                    audio_bytes = None
                '''
                if AudioStart.is_type(event.type): 
                    _LOGGER.debug("received audiostart from mic service")
                    #continue

                #await self.event_from_mic(event, audio_bytes)
                #_LOGGER.debug("sending event from mic task")
                await self.handle_event(event)
            except asyncio.CancelledError:
                _LOGGER.debug("mic asyncio canceled error")
                break
            except Exception:
                _LOGGER.exception("Unexpected error in mic read task")
                await _disconnect()
                mic_client = None  # reconnect
                await asyncio.sleep(self.config_info["service_reconnect_seconds"])

        await _disconnect()

    def _process_mic_audio(self, audio_bytes: bytes) -> bytes:
        """Perform audio pre-processing on mic input."""
        #if self.config_info["mic"]["volume_multiplier"] != 1.0:
        #    audio_bytes = multiply_volume(
        #        audio_bytes, self.config_info["mic"]["volume_multiplier"]
        #    )

        #if self._mic_webrtc is not None:
        #    # Noise suppression and auto gain
        #    audio_bytes = self._mic_webrtc(audio_bytes)

        return audio_bytes

    # -------------------------------------------------------------------------
    # Sound
    # -------------------------------------------------------------------------

    async def event_to_snd(self, event: Event) -> None:
        """Send an event to the sound service."""
        if self._snd_queue is not None:
            self._snd_queue.put_nowait(event)

    '''
        this is the processing task for sound output
    '''
    async def _snd_task_proc(self, address) -> None:
        """text to speech service loop."""
        snd_client: Optional[AsyncClient] = None
        audio_bytes: Optional[bytes] = None
        to_service_task: Optional[asyncio.Task] = None
        from_service_task: Optional[asyncio.Task] = None
        pending: Set[asyncio.Task] = set()

        async def _disconnect() -> None:
            nonlocal to_service_task, from_service_task
            try:
                if snd_client is not None:
                    await snd_client.disconnect()

                # Clean up tasks
                if to_service_task is not None:
                    to_service_task.cancel()
                    to_service_task = None

                if from_service_task is not None:
                    from_service_task.cancel()
                    from_service_task = None
            except Exception:
                pass  # ignore disconnect errors        

        while self.is_running:
            try:
                if self._snd_queue is None:
                    self._snd_queue = asyncio.Queue()

                if snd_client is None:
                    snd_client = AsyncClient.from_uri("tcp://"+address)
                    assert snd_client is not None
                    try:
                        await snd_client.connect()
                        _LOGGER.debug("Connected to snd service")
                    except:
                        _LOGGER.debug("snd connect failed, wait retry")
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        continue                        

                    # Reset
                    from_service_task = None
                    to_service_task = None
                    pending = set()
                    self._snd_queue = asyncio.Queue()

                # Read/write in "parallel"
                if to_service_task is None:
                    # From satellite to wake service
                    to_service_task = asyncio.create_task(
                        self._snd_queue.get(), name="to_snd_service"
                    )
                    pending.add(to_service_task)

                if from_service_task is None:
                    # From wake service to satellite
                    from_service_task = asyncio.create_task(

                        snd_client.read_event(), name="from_snd_service"
                    )
                    pending.add(from_service_task)

                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                if to_service_task in done:
                    # Event to go to snd service (speech reco)
                    _LOGGER.debug("in snd to service")
                    assert to_service_task is not None
                    event = to_service_task.result()
                    to_service_task = None
                    _LOGGER.debug("snd event out = %s",event.type)
                    await snd_client.write_event(event)

                if from_service_task in done:
                    # Event from snd service (detection)
                    _LOGGER.debug("in snd from service")                    
                    assert from_service_task is not None
                    try:
                        event = from_service_task.result()
                        _LOGGER.debug("snd event in = %s",event.type)
                        from_service_task = None
                    except:
                        event = None
                        pass                        

                    if event is None:
                        _LOGGER.warning("snd service disconnected")
                        await _disconnect()
                        snd_client = None  # reconnect
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        continue

                    _LOGGER.debug("sending received snd event on to mainline")
                    await self.handle_event(event)
            except asyncio.CancelledError:
                _LOGGER.debug("snd asyncio canceled error")
                break
            except Exception:
                _LOGGER.exception("Unexpected error in mic read task")
                await _disconnect()
                snd_client = None  # reconnect
                await asyncio.sleep(self.config_info["service_reconnect_seconds"])

        await _disconnect() 

    def _process_snd_audio(self, audio_bytes: bytes) -> bytes:
        """Perform audio pre-processing on snd output."""
        '''if self.config_info["snd"]["volume_multiplier"] != 1.0:
            audio_bytes = multiply_volume(
                audio_bytes, self.config_info["snd"]["volume_multiplier"]
            )
        '''
        return audio_bytes

    '''async def _play_wav(self, wav_path: Optional[Union[str, Path]]) -> None:
        """Send WAV as events to sound service."""
        if (not wav_path) or (not self.config_info["snd"]["enabled"]):
            return

        for event in wav_to_events(
            wav_path,
            samples_per_chunk=self.config_info["snd"]["samples_per_chunk"],
            volume_multiplier=self.config_info["snd"]["volume_multiplier"],
        ):
            await self.event_to_snd(event)
    '''
    # -------------------------------------------------------------------------
    # Wake
    # -------------------------------------------------------------------------

    async def event_from_wake(self, event: Event) -> None:
        """Called when an event is received from the wake service."""

    async def event_to_wake(self, event: Event) -> None:
        """Send event to the wake service."""
        if self._wake_queue is not None:
            self._wake_queue.put_nowait(event)

    '''
        this is the processing task for wakeword detection
    '''            
    async def _wake_task_proc(self,address) -> None:
        """Wake service loop."""
        wake_client: Optional[AsyncClient] = None
        to_service_task: Optional[asyncio.Task] = None
        from_service_task: Optional[asyncio.Task] = None
        pending: Set[asyncio.Task] = set()

        async def _disconnect() -> None:
            nonlocal to_service_task, from_service_task
            try:
                if wake_client is not None:
                    _LOGGER.debug("wake client disconnecting on purpose")
                    await wake_client.disconnect()
                    wake_client = None

                # Clean up tasks
                if to_service_task is not None:
                    to_service_task.cancel()
                    to_service_task = None

                if from_service_task is not None:
                    from_service_task.cancel()
                    from_service_task = None
            except Exception:
                pass  # ignore disconnect errors

        while self.is_running:
            try:
                if self._wake_queue is None:
                    self._wake_queue = asyncio.Queue()

                if wake_client is None:
                    wake_client = AsyncClient.from_uri("tcp://"+address)
                    assert wake_client is not None
                    try:
                        await wake_client.connect()
                        _LOGGER.debug("Connected to wakeword service")
                    except:
                        _LOGGER.debug("wakeword connect failed")
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        wake_client = None
                        continue

                    # Reset
                    from_service_task = None
                    to_service_task = None
                    pending = set()
                    self._wake_queue = asyncio.Queue()

                    # Inform wake service of which wake word(s) to detect
                    await self._send_wake_detect()

                # Read/write in "parallel"
                if to_service_task is None:
                    # From satellite to wake service
                    to_service_task = asyncio.create_task(
                        self._wake_queue.get(), name="to_wake_service"
                    )
                    pending.add(to_service_task)

                if from_service_task is None:
                    # From wake service to satellite
                    from_service_task = asyncio.create_task(
                        wake_client.read_event(), name="from_wake_service"
                    )
                    pending.add(from_service_task)

                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )

                if to_service_task in done:
                    # Event to go to wake service (audio)
                    #_LOGGER.debug("in wake to service")
                    assert to_service_task is not None
                    event = to_service_task.result()
                    to_service_task = None
                    #_LOGGER.debug("wake event out = %s",event.type)
                    await wake_client.write_event(event)

                if from_service_task in done:
                    # Event from wake service (detection)
                    _LOGGER.debug("in wake from service")                    
                    assert from_service_task is not None
                    try:
                        event = from_service_task.result()
                        _LOGGER.debug("wake event in = %s",event.type)
                        from_service_task = None
                    except:
                        event = None
                        pass

                    if event is None:
                        _LOGGER.warning("Wake service disconnected")                        
                        await _disconnect()
                        wake_client = None  # reconnect
                        await asyncio.sleep(self.config_info["service_reconnect_seconds"])
                        continue

                    _LOGGER.debug("sending received wakeword event on to mainline")
                    await self.handle_event(event)

            except asyncio.CancelledError:
                _LOGGER.debug("wake asyncio canceled error")
                continue
            except Exception:
                _LOGGER.exception("Unexpected error in wake read task")
                await _disconnect()
                wake_client = None  # reconnect
                await asyncio.sleep(self.config_info["service_"])

        await _disconnect()

    async def _send_wake_detect(self) -> None:
        """Inform wake word service of which wake words to detect."""
        _LOGGER.debug("sending hotword list to wakeword service")
        await self.event_to_wake(Detect(names=["smart_mirror"]).event())
        #await self.trigger_detect()
