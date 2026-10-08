"""JSON API for the Next.js board. Listens on loopback unless Docker publishes the port."""

from fastapi import FastAPI

from jobhunt.web import api


def create_app() -> FastAPI:
    app = FastAPI(title="Job Hunt OS")
    app.include_router(api.router)
    return app
