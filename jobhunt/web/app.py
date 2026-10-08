"""Local filter UI. The process listens on loopback unless Docker publishes the port."""

from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobhunt.db import tx
from jobhunt.web import board

_ROOT = Path(__file__).resolve().parent
_templates = Jinja2Templates(directory=_ROOT / "templates")


def create_app() -> FastAPI:
    app = FastAPI(title="Job Hunt OS")
    app.mount("/static", StaticFiles(directory=_ROOT / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        return _board(request)

    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request) -> HTMLResponse:
        return _board(request)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int) -> HTMLResponse:
        with tx() as conn:
            job = board.get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return _templates.TemplateResponse(request, "detail.html", {"job": job})

    @app.post("/jobs/{job_id}/events", response_class=HTMLResponse)
    def job_event(
        request: Request,
        job_id: int,
        status: str = Form(...),
        reason: str = Form(""),
    ) -> HTMLResponse:
        with tx() as conn:
            if board.get_job(conn, job_id) is None:
                raise HTTPException(status_code=404)
            try:
                board.record_event(conn, job_id, status, reason.strip() or None)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            job = board.get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return _templates.TemplateResponse(request, "card.html", {"job": job})

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request) -> HTMLResponse:
        with tx() as conn:
            rows = board.list_runs(conn)
        return _templates.TemplateResponse(request, "runs.html", {"runs": rows})

    return app


def _board(request: Request) -> HTMLResponse:
    filters = board.parse_filters(dict(request.query_params))
    with tx() as conn:
        jobs, total = board.list_jobs(conn, filters)
    pages = max(1, (total + board.PAGE_SIZE - 1) // board.PAGE_SIZE)
    context = {
        "jobs": jobs,
        "total": total,
        "filters": filters,
        "pages": pages,
        "query": board.filter_query(filters),
        "prev_query": board.filter_query(filters, page=max(1, filters["page"] - 1)),
        "next_query": board.filter_query(filters, page=min(pages, filters["page"] + 1)),
    }
    template = "jobs.html" if request.headers.get("hx-request") else "board.html"
    if request.url.path == "/jobs" and request.headers.get("hx-request"):
        template = "jobs.html"
    return _templates.TemplateResponse(request, template, context)
