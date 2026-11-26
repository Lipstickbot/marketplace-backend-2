from uuid import uuid4

from starlette.responses import JSONResponse


class BodySizeLimit:
    """Buffer bounded request bodies before multipart/JSON parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PATCH", "PUT"}:
            return await self.app(scope, receive, send)
        maximum = 11 * 1024 * 1024 if scope["path"] in {"/files/upload", "/api/files/upload"} else 512 * 1024
        if scope["path"] in {"/agents/business-analytics/run", "/api/agents/business-analytics/run"}:
            maximum = 896 * 1024  # bound JSON escaping overhead separately from the UTF-8 dataset limit
        messages, size = [], 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                break
            size += len(message.get("body", b""))
            if size > maximum:
                response = JSONResponse({"error": {"code": "payload_too_large", "message": "Запрос слишком большой.",
                    "request_id": scope.get("state", {}).get("request_id", uuid4().hex)}}, status_code=413)
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        async def replay():
            return messages.pop(0) if messages else await receive()
        return await self.app(scope, replay, send)
