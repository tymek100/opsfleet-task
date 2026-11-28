"""Disposable real HTTP browser fixture; never loads provider credentials."""

import asyncio
import tempfile
from pathlib import Path

import uvicorn
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from retail_insight.config import Settings
from retail_insight.interfaces.gui import create_app

ROOT = Path(__file__).resolve().parents[2]
state = Path(tempfile.mkdtemp(prefix="retail-gui-preview-"))
cancelled = []


class PreviewTeam:
    def __init__(self):
        self.history = {}

    async def ask(self, role, question, owner, context, **kwargs):
        if question == "Wait for cancellation":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(role)
                raise
        await asyncio.sleep(0.2)
        if question == "Fail safely":
            raise RuntimeError("Never expose this internal detail")
        if question == "Incomplete answer":
            return {"status": "incomplete", "markdown": "The available evidence is insufficient."}
        key = (role, owner, context)
        previous = self.history.get(key, 0)
        self.history[key] = previous + 1
        text = f"## {role.title()} analysis\n\nReviewed answer. Previous turns: {previous}.\n\n### Revenue\n\n| Product | Revenue |\n|---|---:|\n| Coat | 259.99 |\n| Dress | 120.50 |\n\n### Customer reach\n\n| Product | Customers |\n|---|---:|\n| Dress | 3 |\n| Coat | 2 |"
        return {
            "status": "approved",
            "markdown": text,
            "usage": {"accounted_usd": 0},
            "context_id": context,
        }

    def forget(self, role, owner, context):
        self.history.pop((role, owner, context), None)

    def close(self):
        pass


async def preview_status(request):
    return JSONResponse({"cancelled": cancelled})


settings = Settings(gemini_api_key=SecretStr("offline"), backend="fixture", data_dir=state)
gui = create_app(
    settings,
    PreviewTeam(),
    data_dir=state / "gui",
    static_dir=ROOT / "web/dist",
    port=8765,
    profile="scripted-browser-check",
)
app = Starlette(
    lifespan=gui.router.lifespan_context,
    routes=[Route("/preview-status", preview_status), Mount("/", app=gui)],
)
app.state = gui.state
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
