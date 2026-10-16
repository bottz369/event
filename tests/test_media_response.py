"""画像配信の ASGI 応答順を確認する(DB・Storage へのアクセスなし)。"""
import asyncio
import io

import pytest
from PIL import Image

gzip_module = pytest.importorskip(
    "streamlit.web.server.starlette.starlette_gzip_middleware"
)


@pytest.mark.parametrize("accept_encoding", [b"gzip, deflate, br", b"identity"])
def test_png_response_starts_before_body(accept_encoding):
    """ブラウザに送る PNG が、ヘッダ→本文の順で欠損なく届くこと。"""
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="PNG")
    png = buf.getvalue()

    async def run():
        messages = []

        async def app(scope, receive, send):
            await send({
                "type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"image/png")],
            })
            await send({"type": "http.response.body", "body": png})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            if not messages:
                assert message["type"] == "http.response.start", (
                    "Expected ASGI message 'http.response.start', "
                    f"but got '{message['type']}'."
                )
            messages.append(message)

        middleware = gzip_module.SelectiveGZipMiddleware(app)
        await middleware({
            "type": "http", "path": "/media/preview.png",
            "headers": [(b"accept-encoding", accept_encoding)],
        }, receive, send)
        assert messages[0]["status"] == 200
        body = b"".join(m.get("body", b"") for m in messages[1:])
        import gzip
        if dict(messages[0]["headers"]).get(b"content-encoding") == b"gzip":
            body = gzip.decompress(body)
        assert body == png

    asyncio.run(run())
