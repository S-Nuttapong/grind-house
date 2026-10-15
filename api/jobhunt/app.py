"""JSON API for the Next.js board. Listens on loopback unless Docker publishes the port."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from jobhunt.brag import router as brag_router
from jobhunt.fit import router as fit_router
from jobhunt.jobs import router as jobs_router
from jobhunt.profile import router as profile_router
from jobhunt.resume import router as resume_router
from jobhunt.scrape import router as scrape_router
from jobhunt.scrape.searches_router import router as searches_router


def create_app() -> FastAPI:
    app = FastAPI(title="Job Hunt OS")

    @app.exception_handler(PoolTimeout)
    def database_busy(_request: Request, _exc: PoolTimeout) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "database is busy"})
    for router in (
        jobs_router.router,
        scrape_router.router,
        searches_router,
        profile_router.router,
        brag_router.router,
        fit_router.router,
        resume_router.router,
    ):
        app.include_router(router)
    return app
