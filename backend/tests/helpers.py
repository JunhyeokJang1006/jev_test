import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.main import app


def request(method: str, path: str, **kwargs) -> Response:
    async def send() -> Response:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())
