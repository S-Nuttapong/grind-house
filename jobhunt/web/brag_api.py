"""Brag doc, tag, and metric key routes."""

import re
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from jobhunt.db import brag_repo, tx

router = APIRouter(prefix="/api")

_LINK = re.compile(r"https?://\S+")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color_hex: str | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned

    @field_validator("color_hex")
    @classmethod
    def check_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _COLOR.fullmatch(value) is None:
            raise ValueError("color must be #RRGGBB")
        return value


class MetricKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name is required")
        return cleaned


class MetricIn(BaseModel):
    metric_key_id: int = Field(gt=0)
    value: str = Field(min_length=1, max_length=300)

    @field_validator("value")
    @classmethod
    def strip_value(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("metric value is required")
        return cleaned


class AttachmentIn(BaseModel):
    type: Literal["url"] = "url"
    link: str = Field(max_length=2000)

    @field_validator("link")
    @classmethod
    def check_link(cls, value: str) -> str:
        cleaned = value.strip()
        if _LINK.fullmatch(cleaned) is None:
            raise ValueError("link must start with http:// or https://")
        return cleaned


class BragDocIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    date: date
    company: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    description_md: str = Field(default="", max_length=20_000)
    tag_ids: list[int] = Field(default_factory=list, max_length=40)
    metrics: list[MetricIn] = Field(default_factory=list, max_length=30)
    attachments: list[AttachmentIn] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title is required")
        return cleaned

    @field_validator("company", "role")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


@router.get("/tags")
def list_tags() -> list[dict[str, Any]]:
    with tx() as conn:
        return brag_repo.list_tags(conn)


@router.post("/tags")
def create_tag(body: TagIn) -> dict[str, Any]:
    with tx() as conn:
        tag, created = brag_repo.get_or_create_tag(conn, body.name, body.color_hex)
    return {**tag, "created": created}


@router.get("/metric-keys")
def list_metric_keys() -> list[dict[str, Any]]:
    with tx() as conn:
        return brag_repo.list_metric_keys(conn)


@router.post("/metric-keys")
def create_metric_key(body: MetricKeyIn) -> dict[str, Any]:
    with tx() as conn:
        key, created = brag_repo.get_or_create_metric_key(conn, body.name)
    return {**key, "created": created}


@router.get("/brag-docs/companies")
def list_companies() -> list[str]:
    with tx() as conn:
        return brag_repo.list_companies(conn)


@router.get("/brag-docs")
def list_brag_docs() -> list[dict[str, Any]]:
    with tx() as conn:
        return [_public(doc) for doc in brag_repo.list_brag_docs(conn)]


@router.post("/brag-docs", status_code=201)
def create_brag_doc(body: BragDocIn) -> dict[str, Any]:
    with tx() as conn:
        _require_ids(conn, body)
        doc_id = brag_repo.next_brag_doc_id(conn)
        stored = brag_repo.save_brag_doc(conn, _record(doc_id, body, origin="ui"))
    return _public(stored)


@router.get("/brag-docs/{doc_id}")
def get_brag_doc(doc_id: str) -> dict[str, Any]:
    with tx() as conn:
        stored = brag_repo.get_brag_doc(conn, doc_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="no such brag doc")
    return _public(stored)


@router.put("/brag-docs/{doc_id}")
def update_brag_doc(doc_id: str, body: BragDocIn) -> dict[str, Any]:
    with tx() as conn:
        existing = brag_repo.get_brag_doc(conn, doc_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="no such brag doc")
        _require_ids(conn, body)
        stored = brag_repo.save_brag_doc(
            conn, _record(doc_id, body, origin=str(existing["origin"]))
        )
    return _public(stored)


@router.delete("/brag-docs/{doc_id}", status_code=204)
def delete_brag_doc(doc_id: str) -> None:
    with tx() as conn:
        if not brag_repo.delete_brag_doc(conn, doc_id):
            raise HTTPException(status_code=404, detail="no such brag doc")


def _require_ids(conn: Any, body: BragDocIn) -> None:
    if not brag_repo.tags_exist(conn, body.tag_ids):
        raise HTTPException(status_code=422, detail="unknown tag")
    key_ids = [metric.metric_key_id for metric in body.metrics]
    if not brag_repo.metric_keys_exist(conn, key_ids):
        raise HTTPException(status_code=422, detail="unknown metric key")


def _record(doc_id: str, body: BragDocIn, *, origin: str) -> dict[str, Any]:
    return {
        "id": doc_id,
        "title": body.title,
        "date": body.date,
        "company": body.company,
        "role": body.role,
        "description_md": body.description_md,
        "origin": origin,
        "tag_ids": body.tag_ids,
        "metrics": [metric.model_dump() for metric in body.metrics],
        "attachments": [item.model_dump() for item in body.attachments],
    }


def _public(doc: dict[str, Any]) -> dict[str, Any]:
    stored = dict(doc)
    if isinstance(stored["date"], date):
        stored["date"] = stored["date"].isoformat()
    updated = stored["updated_at"]
    if isinstance(updated, datetime):
        stored["updated_at"] = updated.isoformat()
    return stored
