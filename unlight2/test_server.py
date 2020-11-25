from server import Server
from simple_http import SimpleHttp
import asyncio

server = Server(("127.0.0.1", 9919), SimpleHttp)
server.run()
