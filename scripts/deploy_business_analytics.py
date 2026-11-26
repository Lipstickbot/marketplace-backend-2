"""Deploy the tested Git revision, check real runtime and then update the existing catalog card."""
import asyncio
import os

import httpx

from backend.app.business_analytics import SLUG, activate
from backend.app.config import Settings
from backend.app.runtime_store import RuntimeStore


async def deploy(client, service, revision):
    path = f"https://api.render.com/v1/services/{service}/deploys"
    response = await client.post(path, json={"commitId": revision})
    response.raise_for_status()
    deploy_id = response.json()["id"]
    for _ in range(90):
        response = await client.get(f"{path}/{deploy_id}")
        response.raise_for_status()
        deployment = response.json()
        status = deployment["status"]
        if status == "live":
            if deployment.get("commit", {}).get("id") != revision:
                raise RuntimeError("Render is running a different revision")
            print(f"Render service {service} is live at {revision}", flush=True)
            return
        if status in {"build_failed", "pre_deploy_failed", "update_failed", "canceled", "deactivated"}:
            raise RuntimeError(f"Render deploy failed: {status}")
        await asyncio.sleep(10)
    raise RuntimeError("Render deploy timed out")


async def activate_healthy(client, backend_url, revision, store):
    probe = await client.get(f"{backend_url}/api/health/business-analytics")
    probe.raise_for_status()
    if probe.json() != {"status": "ok", "agent": SLUG, "revision": revision}:
        raise RuntimeError("Smoke test did not confirm business analytics on the deployed revision")
    await activate(store)


async def main():
    revision = os.environ["GITHUB_SHA"]
    backend_service = os.environ["RENDER_BACKEND_SERVICE_ID"]
    frontend_service = os.environ["RENDER_FRONTEND_SERVICE_ID"]
    backend_url = os.environ["RENDER_BACKEND_URL"].rstrip("/")
    settings = Settings.from_env()
    async with httpx.AsyncClient(timeout=30, headers={"Authorization": "Bearer " + os.environ["RENDER_API_KEY"]},
                                 trust_env=False) as render, httpx.AsyncClient(timeout=90, trust_env=False) as runtime:
        store = RuntimeStore(settings, runtime)
        store.require_configured()
        await deploy(render, backend_service, revision)
        await activate_healthy(runtime, backend_url, revision, store)
        print("Verified analytics and activated its existing catalog card", flush=True)
        await deploy(render, frontend_service, revision)


if __name__ == "__main__":
    asyncio.run(main())
