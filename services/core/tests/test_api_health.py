import httpx
from asgi_lifespan import LifespanManager

from llm_stack_api.app import create_app


async def test_healthz_reports_ok() -> None:
    app = create_app()

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
