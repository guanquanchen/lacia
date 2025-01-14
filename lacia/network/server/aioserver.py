import asyncio
import json
from logging import info

from aiohttp import web, WSCloseCode
import aiohttp

from ..abcbase import BaseServer
from ...logs import logger
from ...utils import CallObj
from ...exception import WebSocketClosedError
from ...typing import Message, Optional, Tuple, List


class AioServer(BaseServer):
    def __init__(self) -> None:
        self.app = web.Application()
        self.active_connections: List[Tuple[web.WebSocketResponse, asyncio.Event]] = []

    def start(
        self,
        path: str,
        host: str,
        port: int,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None: # TODO: 更友好的终端提示
        self.loop = loop or asyncio.get_event_loop()
        self.app.add_routes([web.get(path, self.websocket_handler)])
        web.run_app(self.app, host=host, port=port, print=logger.info, loop=loop)  # type: ignore

    async def websocket_handler(self, request):
        event = asyncio.Event()
        ws = web.WebSocketResponse(autoclose=False)
        await ws.prepare(request)
        self.active_connections.append((ws, event))
        logger.success(f"{str(ws)} connected.")
        self.on_ws_callback.add_args(ws)
        await self.on_ws_callback.method(ws)
        # self.loop.create_task(self.on_ws_callback())
        await event.wait()
        return ws

    def disconnect(self, websocket: web.WebSocketResponse):
        for ws, event in self.active_connections:
            if ws == websocket:
                event.set()
                self.active_connections.remove((ws, event))
                break

    async def receive(self, websocket: web.WebSocketResponse):
        data = await websocket.receive()
        if data.type == aiohttp.WSMsgType.CLOSED:
            await self.close_ws(websocket)
            raise WebSocketClosedError(f"{self.__class__.__name__} closed.")
        else:
            return data

    async def receive_json(self, websocket: web.WebSocketResponse):
        data = await self.receive(websocket)
        if data.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(data.data) # type: ignore
            logger.info(f"{self.__class__.__name__} received: {data}")
            return data

    async def receive_bytes(self, websocket: web.WebSocketResponse):
        data = await self.receive(websocket)
        if data.type == aiohttp.WSMsgType.BINARY:
            return data.data

    async def iter_bytes(self, websocket: web.WebSocketResponse):
        while True:
            data = await self.receive_bytes(websocket)
            if data:
                yield data

    async def iter_json(self, websocket: web.WebSocketResponse):
        while True:
            data = await self.receive_json(websocket)
            if data:
                yield data

    async def send_json(self, websocket: web.WebSocketResponse, message: dict):
        return await websocket.send_json(message)

    async def send_bytes(self, websocket: web.WebSocketResponse, message: bytes):
        return await websocket.send_bytes(message)

    async def close_ws(self, websocket: web.WebSocketResponse):
        self.disconnect(websocket)
        logger.info(f"{str(websocket)} disconnected.")
        # return await websocket.close()

    async def close(self):
        ...

    async def on_shutdown(self):
        for ws,event in self.active_connections:
            await ws.close(code=WSCloseCode.GOING_AWAY, message=b"Server shutdown")
            event.set()

    def set_on_ws(self, func, *args, **kwargs):
        self.on_ws_callback = CallObj(method=func, args=args, kwargs=kwargs)