"""Disposable real HTTP/SSE browser fixture. Never loads provider credentials."""

import asyncio
import tempfile
from pathlib import Path

import uvicorn
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

import retail_insight.a2a.server as server
from retail_insight.config import Settings
from retail_insight.contracts import Answer, TurnResult
from retail_insight.interfaces.gui import AGENTS, create_app
from tests.multi_agent.test_transport import ReviewedRuntime

ROOT = Path(__file__).resolve().parents[2]
state = Path(tempfile.mkdtemp(prefix="retail-gui-preview-"))
SECRET = "offline-preview-signing-key-at-least-thirty-two-characters"
TOKEN = "offline-preview-workspace-token"
cancelled = []


class PreviewRuntime(ReviewedRuntime):
    async def ask(self, question, **kwargs):
        if question == "Wait for cancellation":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(self.role)
                raise
        await asyncio.sleep(0.2)
        if question == "Fail safely":
            raise RuntimeError("Never expose this internal detail")
        if question == "Incomplete answer":
            return TurnResult(
                None, "incomplete", "The available evidence is insufficient.", [], {}, [], 0.2
            )
        previous = len(self.history)
        text = f"## {self.role.title()} analysis\n\nReviewed answer. Previous turns: {previous}.\n\n### Revenue\n\n| Product | Revenue |\n|---|---:|\n| Coat | 259.99 |\n| Dress | 120.50 |\n\n### Customer reach\n\n| Product | Customers |\n|---|---:|\n| Dress | 3 |\n| Coat | 2 |"
        answer = Answer("A1", text, [], "answer", True)
        self.answers["A1"] = answer
        self.history.append({"question": question, "answer": text})
        return TurnResult(answer, "approved", "", [], {"accounted_usd": 0}, [], 0.2)


server.create_agent = PreviewRuntime
catalog = {role: {"url": f"http://127.0.0.1:8765/services/{role}"} for role in AGENTS}
routes = []
for role in AGENTS:
    settings = Settings.model_construct(
        gemini_api_key=SecretStr("offline"),
        backend="fixture",
        data_dir=state / role,
        turn_timeout_seconds=180,
        question_budget_usd=1,
    )
    routes.append(
        Mount(
            f"/services/{role}",
            app=server.create_app(
                role, settings, secret=SECRET, access_token=TOKEN, public_url=catalog[role]["url"]
            ),
        )
    )


async def preview_status(request):
    return JSONResponse({"cancelled": cancelled})


gui = create_app(
    catalog,
    TOKEN,
    data_dir=state / "gui",
    static_dir=ROOT / "web/dist",
    port=8765,
    profile="scripted-browser-check",
)
# Starlette does not run nested applications' lifespan automatically.
app = Starlette(
    lifespan=gui.router.lifespan_context,
    routes=[Route("/preview-status", preview_status), *routes, Mount("/", app=gui)],
)
app.state = gui.state

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
