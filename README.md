
this is a test implementation of the full Wyoming stack to replace similar function is a standalone application
replacing the nodejs sonus library (which does mic/hotword and reco(via google speech))

you need to start two apps at the same time after configuration

cd sonushandler 

you need to edit the config.json to identify where the appropriate services are located

this runs the full engine, mic/hotword/and reco via connected services defined in config.json
they can be local, in docker, or remote
```text
microphone(mic)
hotword (wake/hotword)
speech to text (asr)
tts (text to speech)  // coming soon
snd (sound out)       // coming soon
```
in the config file
```json
{   
    "mic_address": "localhost:10600",
    "wake_address": "localhost:10400",
    "asr_address": "localhost:10555",
    "tts_address": "localhost:10200",
    "snd_address": "localhost:10601",
}
```
(pick some port availabe on the system you are running this on)

```sh
script/run --uri=tcp://localhost:9876 --debug --config=$(pwd)/sonushandler/config.json 2>&1 | tee -a somefile.txt
```

this supports a new Event type sent from the outside, Speak("text to speak") 
this does the Synthesize(using the configured service endpoint, config.json again) and audio play (to the sound out service) 


the app connected can send the Speek(text="......")  request (in json format) // coming soon

in Addition the outside app will be informed of two events
Hotword() detected
and 
Command("text of command" )
  this would normally be input to the intent service

but my app has its own intent handler.. just needs the voice recognized text 

the second app sample is tests/test_wyoming.js written in Javascript..

it needs the port number used on the sonus server --uri parm (9876 above) 
it is the APP that needs mic/hotword/rec  services





