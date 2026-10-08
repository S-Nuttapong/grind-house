"""JSON API for the Next.js board. Listens on loopback unless Docker publishes the port."""

from fastapi import FastAPI

from jobhunt.web import api, brag_api, fit_api


def create_app() -> FastAPI:
    app = FastAPI(title="Job Hunt OS")
    app.include_router(api.router)
    app.include_router(brag_api.router)
    app.include_router(fit_api.router)
    return app
