import base64, json, unittest, uuid
from serial_service import Dispatcher, FrameReader, allowed

class Tests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        def call(method,path,body):
            self.calls.append((method,path,body));return 200,'{"ssid":"测试网络"}'.encode()
        self.dispatcher=Dispatcher('test-token',call)
    def frame(self,**changes):
        frame=dict(v=1,id=str(uuid.uuid4()),token='test-token',method='GET',path='/api/wifi/status',body='')
        frame.update(changes);return frame
    def test_auth_and_hello(self):
        self.assertEqual(self.dispatcher.handle(self.frame(token='bad'))['status'],401)
        self.assertEqual(self.calls,[])
        r=self.dispatcher.handle(self.frame(method='HELLO'))
        self.assertEqual(json.loads(base64.b64decode(r['body']))['protocol'],'usb-ai-serial')
    def test_rotated_token(self):
        current=['test-token'];d=Dispatcher(lambda:current[0],lambda *args:(200,b'{}'))
        self.assertEqual(d.handle(self.frame())['status'],200)
        current[0]='new-token'
        self.assertEqual(d.handle(self.frame())['status'],401)
        self.assertEqual(d.handle(self.frame(token='new-token'))['status'],200)
    def test_endpoints(self):
        for route in ['https://example.com','//example.com','/api/../api/status','/api/status?target=example.com','/api/proxy','/api/workbench/session?id=../settings']:
            self.assertFalse(allowed('GET',route))
            self.assertEqual(self.dispatcher.handle(self.frame(path=route))['status'],403)
        self.assertEqual(self.calls,[])
        r=self.dispatcher.handle(self.frame())
        self.assertEqual(json.loads(base64.b64decode(r['body']))['ssid'],'测试网络')
    def test_post_limits_and_body(self):
        for body in [b'[]',b'not json',b' '*400001]:
            self.assertEqual(self.dispatcher.handle(self.frame(method='POST',path='/api/wifi',body=base64.b64encode(body).decode()))['status'],400)
        self.assertEqual(self.calls,[])
        body=json.dumps({'ssid':'coco','password':'fixture-only'}).encode()
        self.assertEqual(self.dispatcher.handle(self.frame(method='POST',path='/api/wifi',body=base64.b64encode(body).decode()))['status'],200)
        self.assertEqual(self.calls[0][2],body)
    def test_fragmented_frames(self):
        a,b=self.frame(),self.frame(method='HELLO')
        wire=(json.dumps(a)+'\n'+json.dumps(b)+'\n').encode()
        reader=FrameReader();found=[]
        for i in range(0,len(wire),7): found+=reader.feed(wire[i:i+7])
        self.assertEqual(found,[a,b])
        self.assertEqual(reader.feed(b'garbage\n[]\n{}\n'),[{}])

if __name__=='__main__': unittest.main()
