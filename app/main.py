from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.keitaro import KeitaroError
from app.routers.api import router as api_router
from app.services.creator import CreatorError
from app.services.editor import EditorError

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")

app = FastAPI(title="Adrobot · Keitaro wrapper")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
app.include_router(api_router)


@app.middleware("http")
async def _csrf_guard(request: Request, call_next):
    """Изменяющие запросы к API — только из нашего фронта.

    jQuery сам ставит X-Requested-With на same-origin запросы, а чужой сайт не может
    выставить этот заголовок без CORS-разрешения (CORS у нас не включён).
    """
    if (
        request.url.path.startswith("/api/")
        and request.method not in ("GET", "HEAD", "OPTIONS")
        and request.headers.get("x-requested-with") != "XMLHttpRequest"
    ):
        return JSONResponse(status_code=403, content={"detail": "Нужен заголовок X-Requested-With: XMLHttpRequest"})
    return await call_next(request)


@app.exception_handler(EditorError)
@app.exception_handler(CreatorError)
async def _user_error(_: Request, exc: Exception):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(KeitaroError)
async def _keitaro_error(_: Request, exc: KeitaroError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def _ctx(request: Request, **extra):
    return {"request": request, "keitaro_url": get_settings().keitaro_url.rstrip("/"), **extra}


@app.get("/", response_class=HTMLResponse)
def creator_page(request: Request):
    return templates.TemplateResponse(request, "creator.html", _ctx(request, active="create"))


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request):
    return templates.TemplateResponse(request, "campaigns.html", _ctx(request, active="campaigns"))


@app.get("/campaigns/{keitaro_id}", response_class=HTMLResponse)
def streams_page(request: Request, keitaro_id: int):
    return templates.TemplateResponse(
        request, "streams.html", _ctx(request, active="campaigns", campaign_id=keitaro_id)
    )


@app.get("/health")
def health():
    return {"ok": True}
