"""Local filter UI. The process listens on loopback unless Docker publishes the port."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jobhunt.db import tx
from jobhunt.web import board
from jobhunt.web.render import render_markdown

_ROOT = Path(__file__).resolve().parent
_templates = Jinja2Templates(directory=_ROOT / "templates")
_templates.env.filters["markdown"] = render_markdown


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
        if request.headers.get("hx-request"):
            return _templates.TemplateResponse(request, "detail.html", {"job": job})
        context = _context(request, force_jk=job_id)
        context["job"] = job
        return _templates.TemplateResponse(request, "job_page.html", context)

    @app.post("/jobs/{job_id}/events", response_class=HTMLResponse)
    def job_event(
        request: Request,
        job_id: int,
        status: str = Form(...),
        reason: str = Form(""),
    ) -> HTMLResponse:
        filters = board.parse_filters(_current_params(request))
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
        job["select_query"] = board.filter_query(filters, jk=job_id)
        job["selected"] = True
        response = _templates.TemplateResponse(
            request, "card.html", {"job": job, "filters": filters}
        )
        response.headers["HX-Trigger"] = json.dumps({"jobUpdated": {"id": job_id}})
        return response

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request) -> HTMLResponse:
        with tx() as conn:
            rows = board.list_runs(conn)
        return _templates.TemplateResponse(request, "runs.html", {"runs": rows})

    return app


def _board(request: Request) -> HTMLResponse:
    context = _context(request)
    template = "jobs.html" if request.headers.get("hx-request") else "board.html"
    return _templates.TemplateResponse(request, template, context)


def _context(request: Request, force_jk: int | None = None) -> dict[str, object]:
    params = dict(request.query_params)
    if force_jk is not None:
        params["jk"] = str(force_jk)
    filters = board.parse_filters(params)
    with tx() as conn:
        jobs, total = board.list_jobs(conn, filters)
        selected = board.get_job(conn, int(filters["jk"])) if filters["jk"] else None
    for job in jobs:
        job_id = int(job["id"])
        job["select_query"] = board.filter_query(filters, jk=job_id)
        job["selected"] = filters["jk"] == job_id
    pages = max(1, (total + board.PAGE_SIZE - 1) // board.PAGE_SIZE)
    return {
        "jobs": jobs,
        "total": total,
        "selected": selected,
        "filters": filters,
        "pages": pages,
        "page_links": board.page_links(filters, pages),
        "query": board.filter_query(filters),
        "prev_query": board.filter_query(filters, page=max(1, int(filters["page"]) - 1)),
        "next_query": board.filter_query(filters, page=min(pages, int(filters["page"]) + 1)),
    }


def _current_params(request: Request) -> dict[str, str]:
    current = request.headers.get("hx-current-url") or ""
    parsed = parse_qs(urlparse(current).query)
    params = {key: values[0] for key, values in parsed.items() if values}
    params.update(dict(request.query_params))
    return params
