"""在框架解析表单前约束请求体，并检查浏览器来源。"""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from .common import error_response


class JsonCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers: Headers):
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response
        headers = {k: v for k, v in response.headers.items() if k not in {"content-type", "content-length"}}
        return error_response(403, "LOCAL_ACCESS_DENIED", "此网页来源、方法或请求头未获跨域许可。", headers=headers)


class LocalRequestPolicy:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        host = headers.get("host", "").lower()
        origin = headers.get("origin")
        scheme = {"ws": "http", "wss": "https"}.get(scope["scheme"], scope["scheme"])
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        try:
            hostname = urlsplit("//" + host).hostname
        except ValueError:
            hostname = None
        # 默认回环监听时也检查 Host，避免网页通过 DNS 重绑定访问本地数据。
        host_denied = self.settings.host in local_hosts and hostname not in local_hosts
        origin_denied = origin and origin != f"{scheme}://{host}" and origin not in self.settings.cors_origins
        if host_denied or origin_denied:
            if kind == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await error_response(403, "LOCAL_ACCESS_DENIED", "请求的主机或网页来源未获允许。")(scope, receive, send)

        if kind == "websocket":
            return await self.app(scope, receive, send)
        # 表单留 1 MiB 给 multipart 边界与字段；文件本体在存盘时单独计量。
        overhead = 1024 * 1024
        multipart = headers.get("content-type", "").lower().split(";")[0].strip() == "multipart/form-data"
        limit = self.settings.max_file_bytes + overhead if multipart else overhead
        if (length := headers.get("content-length")) is not None:
            try:
                size = int(length)
                if size < 0:
                    raise ValueError
            except ValueError:
                return await error_response(400, "INVALID_LENGTH", "请求体长度无效。")(scope, receive, send)
            if size > limit:
                return await error_response(413, "REQUEST_TOO_LARGE", "请求体超过大小上限。")(scope, receive, send)
        count = 0

        async def limited_receive():
            nonlocal count
            message = await receive()
            if message["type"] == "http.request":
                count += len(message.get("body", b""))
                if count > limit:
                    raise HTTPException(413, "请求体超过大小上限。")
            return message

        return await self.app(scope, limited_receive, send)
