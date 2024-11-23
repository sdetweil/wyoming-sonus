const net = require('net');
const process = require('process')

if(process.argv.length <3){
   console.log("this app need the port number of the sonus wyoming server, from the --uri parameter")
   process.exit()
} 
const client = net.createConnection({ port: process.argv[2] }, () => {
  // 'connect' listener.
  console.log('connected to server!');
  client.write('{"type":"speak","data":"fribble"}\n');
  console.log("sent to server")
});
client.on('data', (data) => {
  console.log(data.toString());
//  client.end();
});
client.on('end', () => {
  console.log('disconnected from server');
});
