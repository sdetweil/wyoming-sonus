const net = require('net');
const process = require('process')

port = 9876

if(0){
if(process.argv.length <3){
  // console.log("this app need the port number of the sonus wyoming server, from the --uri parameter")
   process.exit()
} 
port=process.argv[2]
}

const client = net.createConnection({ port: port, host:"localhost" })
client.on('data', (data) => {
  console.log("data="+Buffer.from(data, 'ascii').toString('hex'));
  let partsdata=data.toString().replace("\n\n","\n")
  console.log("data 2="+partsdata.toString());
  parts = partsdata.split('\n')
  response = JSON.parse(parts[0])
  console.log("response part 1=",response)
  if(response.type=='hotword')
    console.log("!h:", 0)
  if(response.type=='command')
    try { 
      console.log("!f",JSON.parse(parts[1]).text)
    }
    catch(e){
      console.log("part2="+data)
    }

});
client.on('end', () => {
  console.log('disconnected from server');
});

if(0){
if(client){
  // 'connect' listener.
  console.log('connected to server!');
  client.write('{"type":"describe"}\n');
  console.log("sent to server")
};
console.log("waiting");
}
