#
# simple-http协议是简化版的http协议, 仅以支持http作为游戏服务器为目的
#

from os import environ
import re
from asyncio import Protocol
from time import time
from httptools import HttpRequestParser, HttpParserError, parse_url
import traceback
import orjson as json
from datetime import datetime

from log import unlight_logger

class SimpleHttp(Protocol):
    ''' 暂时不处理流(octet-stream)相关的内容
    一次性send/receive所有字节,即暂不支持流
    媒体相关的内容.
    '''

    def __init__(self, *,
            loop,
            server,
            conns,
            request_limit_size = 1024*1024*8, # 8M
            request_cur_size = 0,
            request_timeout = 60,
            response_timeout = 60,
            keep_alive = 10):

        self.loop = loop
        self.server = server
        self.transport = None
        self.parser = None
        self.request = None
        self.response = None

        self.request_limit_size= request_limit_size
        self.request_cur_size = 0
        self.request_timeout = request_timeout
        self.response_timeout = response_timeout
        self.keep_alive = keep_alive
        self.last_request_time = None

        self.conns = conns
        self.tasks = []

    ############################# conn base
    def connection_made(self, transport):
        self.transport = transport
        remote_addr = transport.get_extra_info("peername") # tuple (ip, port)
        self.remote_addr = remote_addr
        self.conns.add(self)

        self.last_request_time = time()
        self.tasks.append(
                self.loop.call_later(self.request_timeout, self.request_timeout_handler))

    def data_received(self, data):
        if not self.parser:
            self.parser = HttpRequestParser(self)
        if not self.request:
            self.request = Request(self)

        self.request_cur_size += len(data)
        if self.request_cur_size > self.request_limit_size:
            self.write_error(b"Payload Too Large")

        try:
            self.parser.feed_data(data)
        except HttpParserError:
            self.write_error(b"Bad request")
            traceback.print_exc()

    def connection_lost(self, err):
        self.conns.discard(self)
        self.cancel_tasks()
        print(">>>> conn is cloesed.")

    @property
    def is_keep_alive(self):
        should_keep_alive = 1 if self.parser.should_keep_alive else 0
        return should_keep_alive and self.keep_alive 

    def write_response(self, enc_data):
        try:
            self.transport.write(enc_data)
            print(">>>> send msg: ", enc_data)
        except RuntimeError:
            unlight_logger.error("Connection lost before response written @ %s",
                    self.request.ip if self.request else "Unknown")
        finally:
            if self.is_keep_alive:
                self.tasks.append(
                        self.loop.call_later(self.keep_alive, self.keep_alive_timeout_handler))
                self.cleanup()
            else:
                self.transport.close()
                self.transport = None

    def write_error(self, enc_err):
        try:
            self.transport.write(enc_err)
        except RuntimeError:
            unlight_logger.error("Connection lost before error written @ %s",
                    self.request.ip if self.request else "Unknown")
        finally:
            try:
                self.transport.close()
                self.transport = None
            except AttributeError:
                unlight_logger.error("Connection lost before server could close it.")

    def cleanup(self):
        self.request_cur_size = 0
        self.parser = None
        self.request = None

    def cancel_tasks(self):
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()

    def disconnect(self):
        self.transport.close()
        self.transport = None

    def request_timeout_handler(self):
        self.cancel_tasks()
        self.write_error(b"Request Timeout.")

    def response_timeout_handler(self):
        self.cancel_tasks()
        self.write_error(b"Response Timeout.")

    def keep_alive_timeout_handler(self):
        self.cancel_tasks()
        self.transport.close()
        self.transport = None

        print(">>>> KeepAlive Timeout. Closing connection.")

    ############################# 数据解析(目前暂不处理流相关)
    def on_url(self, burl):
        ''' burl: url bytes '''
        self.request.add_burl(burl)

    def on_header(self, bname, bvalue):
        ''' bname: header name bytes
        bvalue: header value bytes
        '''
        self.request.add_bheader(bname, bvalue)
        if bname.lower() == b"content-length" and int(bvalue) > self.request_limit_size:
            self.write_error(b"Payload Too Large.")
        if bname.lower() == b"expect" and bvalue.lower() == b"100-continue":
            self.write_error(b"HTTP 1.1 \r\n\r\n100-continue\r\n")

    def on_header_complete(self):
        self.tasks.append(
                self.loop.call_later(self.response_timeout, self.response_timeout_handler))

    def on_body(self, bbody):
        ''' bbody: body bytes '''
        self.request.add_bbody(bbody)

    def on_message_complete(self):
        response = Response(keep_alive=self.is_keep_alive)
        request_task = self.loop.create_task(
                self.server.handle_request(self.request, response, self.write_response))
        self.tasks.append(request_task)
        


bkey_pattern = re.compile(rb'name="(.*)"')
bfile_key_pattern = re.compile(rb'name="(.*)";')
bfile_suffix_pattern= re.compile(rb'filename=".*(\..*)";')
class Request:

    def __init__(self, transporter):
        ''' 1. utf-8编码(默认) '''
        self.__transporter = transporter
        # bytes
        self.__burl = None
        self.__bheaders = {}
        self.__bbody = None
        # basic data
        self.body = None
        self.raw = None
        self.form = None
        self.json = None
        self.file = None

        #self.ctx = None
        self.init_env()

    def init_env(self):
        base_dir = environ.get("PWD")
        self.env = {"BASE_DIR": base_dir}

    def add_burl(self, burl):
        ''' url当前解析的参数
            _bschema
            _bhost
            _port
            _bpath
            _bfragment
            _buserinfo
            _bquery_params
        '''
        self.__burl = burl
        # url
        url = parse_url(burl)
        self._bschema= url.schema
        self._bhost = url.host
        self._port = 443 if self._bschema == b"https" else 80
        self._bpath = url.path
        self._bfragment = url.fragment
        self._buserinfo = url.userinfo
        bquery_params = {}
        if url.query:
            qs = url.query.split(b"&")
            for q in qs:
                p, v = q.split(b"=")
                bquery_params[p] = v
        self._bquery_params = bquery_params

    def add_bheader(self, bname, bvalue):
        ''' headers
            _bhost
            _bconnection
            _bcontent_type
            _bagent
            _baccept
            _baccept_encoding
            _bcookies
            _bcache_control
            _bcontent_length
            _bboundary
        保留项:
            1. agent阻止指定agent访问
            2. cache-control缓存控制
            3. host跨域
        '''
        bname = bname.strip()
        self.__bheaders[bname] = bvalue
        l_bname = bname.lower()

        if l_bname == b"host":
            self._bhost = bvalue
        elif l_bname == b"connection":
            pass
        elif l_bname == b"content-type":
            self._bcontent_type = bvalue
            if l_bname.find(b"form-data") > -1:
                _, bb = bvalue.split(b";")
                bboundary = bb.split(b"=")[1].strip()
                bboundary = b"--" + bboundary
                self._bboundary = bboundary
        elif l_bname == b"content-length":
            self._bcontent_length = bvalue
        elif l_bname == b"user-agent":
            self._bagent = bvalue
        elif l_bname == b"accept":
            self._baccept = bvalue
        elif l_bname == b"accept-encoding":
            self._baccept_encoding = bvalue
        elif l_bname == b"cookie":
            self._bcookies = bvalue.split(b";")
        elif l_bname == b"cache-control":
            self._bcache_control = bvalue

    def add_bbody(self, bbody):
        ''' 
            1. x-www-form-urlencoded -> self.form + self.raw
            2. form-data             -> self.form
            3. raw(text)             -> self.raw + self.body
            4. raw(json)             -> self.raw + self.json
            5. binary(text)          -> self.file
            6. binary(octect-stream) -> self.file
            7. binary(o-MIME)        -> self.file
        '''
        self.__bbody = bbody
        print(">>>>>> 查看body: ", bbody)
        
        bcontent_type = self._bcontent_type.lower()
        if bcontent_type.find(b"x-www-form-urlencoded") > -1:
            data = bbody.split(b"\r\n\r\n")[1].decode()
            self.raw = data

            items = data.split("&")
            form = {}
            for item in items:
                name, value = item.split("=")
                form[name] = value
            self.form = form
        elif bcontent_type.find(b"form-data") > -1:
            bboundary = self._bboundary
            bdata_list = bbody.split(bboundary)
            form = {}
            for bitem in bdata_list:
                bitem = bitem.strip()
                if bitem and bitem != b"--":
                    if bitem.find(b"\r\n\r\n") > -1:
                        bfdes, bf = bitem.split(b"\r\n\r\n")
                        bkey_list = bfile_key_pattern.findall(bfdes)
                        bsuffix_list = bfile_suffix_pattern.findall(bfdes)
                        if not bkey_list:
                            bkey_list = [str(time()).encode()]
                        if not bsuffix_list:
                            bsuffix_list = [b""]
                        if not bf:
                            self.__transporter.write_error(b"Bad Request.")
                        form[(bkey_list[0]+bsuffix_list[0]).decode()] = bf
                    else:
                        _, bdata = bitem.split(b";")
                        bkey_des, bvalue = bdata.split(b"\r\n\r\n")
                        key = key_pattern.findall(bkey_des)[0].decode()
                        form[key] = bvalue.decode()
            self.form = form
        elif bcontent_type.find(b"text/plain") > -1:
            self.body = self.raw = bbody.decode()
        elif bcontent_type.find(b"json") > -1:
            body = bbody.decode()
            self.body = body
            self.json = json.loads(body)
        elif bcontent_type.find(b"octet-stream") > -1:
            self.body = bbody
            self.file = bbody
        else: # other MIME(no name tag.)
            self.file = bbody
        
    # 读取请求信息(查看时解析)
    # ------------------------
    def get_url(self):
        url = ""
        burl = self.__burl
        url = burl.decode()
        return url

    def get_headers(self):
        headers = {}
        bheaders = self.__bheaders
        for bname, bvalue in bheaders.items():
            name = bname.decode()
            value = bvalue.decode()
            headers[name] = value
        return headers

    def get_raw(self):
        return self.raw

    def get_form(self):
        return self.form

    def get_json(self):
        return self.json

    def get_file(self):
        return self.file # maybe incomplete

gmt_format = "%a, %d %b %Y %H:%M:%S GMT"
class Response:

    def __init__(
            self, 
            version= "1.1", 
            code=200, 
            keep_alive=0):
        self.version = version
        self.code = code
        self.headers = {"Content-Type": "text/plain;charset=utf-8"}
        if keep_alive:
            self.headers.update(
                    {"Connection": "keep-alive",
                     "Keep-Alive": keep_alive})
        else:
            self.headers.update({"Connection": "close"})

    def update_version(self, version):
        if version > self.version:
            self.version = version

    def get_code_status(self, code):
        return STATUS_CODE_MSG.get(code, "")

    def update_headers(self, headers={}):
        self.headers.update(headers)

    def encode_headers(self):
        headers = ""
        hs = self.headers
        hs.update({"Date": datetime.utcnow().strftime(gmt_format)})
        for h, v in hs.items():
            headers += f"{h}: {v}\r\n"
        title = f"HTTP/{self.version} {self.code} {self.get_code_status(self.code)}\r\n"
        return title.encode() + headers.encode()

    def text(self, data):
        enc_data = data.encode()
        self.headers["Content-Type"] = "text/plain"
        self.headers["Content-Length"] = len(enc_data)
        return self.encode_headers() + b"\r\n" + enc_data

    def html(self, data):
        enc_data = data.encode()
        self.headers["Content-Type"] = "text/html"
        self.headers["Content-Length"] = len(enc_data)
        return self.encode_headers() + b"\r\n" + enc_data

    def json(self, data):
        enc_data = json.dumps(data)
        self.headers["Content-Type"] = "application/json"
        self.headers["Content-Length"] = len(enc_data)
        return self.encode_headers() + b"\r\n" + enc_data

    def file(self, bdata):
        self.headers["Content-Type"] = "application/octet-stream"
        self.headers["Content-Length"] = len(bdata)
        return self.encode_headers() + b"\r\n" + bdata


STATUS_CODE_MSG = {
    100: "Continue",
    101: "Switching Protocols",

    200: "OK",
    201: "Created",
    202: "Accepted",
    203: "Non-Authoritative Information",
    204: "No Content",
    205: "Reset Content",	
    206: "Partial Content",	

    300: "Multiple Choices",
    301: "Moved Permanently",
    302: "Found",
    304: "Not Modified",
    305: "Use Proxy",
    307: "Temporary Redirect",	

    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Time-out",
    409: "Conflict",
    411: "Length Required",
    412: "Precondition Failed",
    413: "Request Entity Too Large",
    414: "Request-URI Too Large",
    415: "Unsupported Media Type",
    416: "Requested range not satisfiable",
    417: "Expectation Failed",

    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Time-out",
    505: "HTTP Version not supported",
}
