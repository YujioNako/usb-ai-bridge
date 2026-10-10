using System;
using System.IO;
using System.IO.Ports;
using System.Text;
using System.Threading;

// Unprivileged CDC ACM worker. No networking or command execution.
class SerialWorker {
    static int Main(string[] args) {
        if(args.Length!=1 || !System.Text.RegularExpressions.Regex.IsMatch(args[0],"^COM[0-9]+$")) {
            Console.Error.WriteLine("Usage: SerialWorker.exe COM<number>");return 2;
        }
        using(var port=new SerialPort(args[0],115200,Parity.None,8,StopBits.One)) {
            port.Encoding=Encoding.ASCII;port.ReadTimeout=500;port.WriteTimeout=10000;
            port.DtrEnable=true;port.RtsEnable=true;port.ReadBufferSize=65536;
            try {
                port.Open();Console.Error.WriteLine("Serial port open: "+args[0]);
                var reader=new Thread(delegate() {
                    try {
                        var buffer=new StringBuilder();bool discard=false;
                        var chunk=new byte[16384];
                        while(true) {
                            int count;
                            try { count=port.Read(chunk,0,chunk.Length); } catch(TimeoutException) { continue; }
                            for(int i=0;i<count;i++) {
                                char c=(char)chunk[i];
                                if(c=='\n') {
                                    if(!discard && buffer.Length>0) { Console.Out.WriteLine(buffer.ToString());Console.Out.Flush(); }
                                    buffer.Length=0;discard=false;
                                } else if(!discard) {
                                    buffer.Append(c);
                                    if(buffer.Length>6000000) { buffer.Length=0;discard=true; }
                                }
                            }
                        }
                    } catch(Exception e) { Console.Error.WriteLine(e.Message);Environment.Exit(1); }
                });
                reader.IsBackground=true;reader.Start();
                string line;
                while((line=Console.ReadLine())!=null) {
                    if(line.Length>6000000) throw new IOException("Message too large");
                    port.Write(line+"\n");
                }
                return 0;
            } catch(Exception e) { Console.Error.WriteLine(e.GetType().Name+": "+e.Message);return 1; }
        }
    }
}
