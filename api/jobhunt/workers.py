"""Schedules that start with `jobhunt serve`. HTTP does not wait on them."""

import logging
import os
import threading
import time

from jobhunt.core.log import get_logger

log = get_logger(__name__)

_SCRAPE_SECONDS = 15 * 60
_FIT_SECONDS = 60


def start() -> None:
    """Scrape on the 15-minute schedule, and score jobs every minute."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    threading.Thread(target=_scrape, name="scrape", daemon=True).start()
    threading.Thread(target=_fit, name="fit", daemon=True).start()
    if os.environ.get("ANTHROPIC_API_KEY"):
        threading.Thread(target=_resume, name="resume", daemon=True).start()
    else:
        log.info("resume worker stays a separate process; ANTHROPIC_API_KEY is not set here")


def _scrape() -> None:
    from jobhunt.scrape.tick import tick

    while True:
        try:
            ran = tick()
            log.info("scrape pass finished, %s sources", ran)
        except Exception:
            log.exception("scrape pass failed")
        time.sleep(_SCRAPE_SECONDS)


def _fit() -> None:
    from jobhunt.composition import COMPOSITION
    from jobhunt.fit.pipeline import FitPipeline

    try:
        pipeline = FitPipeline(COMPOSITION)
    except Exception:
        log.exception("fit model failed to load")
        return
    log.info("fit worker ready, %s", COMPOSITION.scorer.model_id)
    while True:
        try:
            pipeline.poll_once()
        except Exception:
            log.exception("fit pass failed")
        time.sleep(_FIT_SECONDS)


def _resume() -> None:
    os.environ["JOBHUNT_ALLOW_OFFSITE"] = "1"
    from jobhunt.composition import COMPOSITION
    from jobhunt.resume.pipeline import ResumePipeline

    log.info("resume worker ready")
    ResumePipeline(COMPOSITION).serve(handle_signals=False)
