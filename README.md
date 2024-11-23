
this is a test implementation of the full Wyoming stack to replace similar function is a standalone application
replacing the nodejs sonus library (which does mic/hotword and reco(via google speech))

you need to start two apps at the same time

cd sonushandler 
script/run --uri=tcp://localhost:9876 --debug --config=$(pwd)/sonushandler/config.json 2>&1 | tee -a somefile.txt

you need to edit the config.json to identify where the appropriate services are located

this runs the full engine, mic/hotword/and reco via conencted services defined in config.json
they can be local, in docker, or remote

this supports a new Event type sent from the outside, Speak("text to speak") 
this does the Synthesize(using the configured service endpoint, config.json again) and audio play (to the sound out service) 

the app connected can send the Speek()  request (in json format) 

in Addition the outside app will be informed of two events
Hotword() detected
and 
Command("text of command" )
  this would normally be input to the intent service

but my app has its own intent handler.. just needs the voice recognized text 

the second app sample is tests/test_wyoming.js written in Javascript..

it needs the port number used on the sonus server --uri parm (9876 above) 




