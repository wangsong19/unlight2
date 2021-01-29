from server import Server
from simple_http import SimpleHttp
import asyncio

# 创建服务
server = Server(("127.0.0.1", 9919), SimpleHttp)

# 添加服务路由处理
@server.router.get("/hello")
async def hello(request, response):
    response.text("hello world!")

server.run()
