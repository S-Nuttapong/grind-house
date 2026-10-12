"""Profile summary and resume routes. Uploads are parsed here; no model runs."""

from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from jobhunt.core.db import tx
from jobhunt.profile import repo as profile_repo

router = APIRouter(prefix="/api")


_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


_UPLOAD_SUFFIXES = {".pdf", ".md", ".txt", ".json"}


class ProfileIn(BaseModel):
    body_md: str


@router.get("/profile/summary")
def get_summary() -> dict[str, str]:
    with tx() as conn:
        return {"body_md": profile_repo.get_bank_profile(conn)}


@router.put("/profile/summary")
def put_summary(body: ProfileIn) -> dict[str, str]:
    with tx() as conn:
        profile_repo.set_bank_profile(conn, body.body_md)
    return {"body_md": body.body_md}


@router.get("/resumes")
def list_resumes() -> list[dict[str, Any]]:
    with tx() as conn:
        return profile_repo.list_resumes(conn)


@router.post("/resumes", status_code=201)
async def upload_resume(file: UploadFile) -> dict[str, Any]:
    name = file.filename or "resume"
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix not in _UPLOAD_SUFFIXES:
        raise HTTPException(status_code=422, detail="upload a .pdf, .md, .txt, or .json file")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file is over 5 MB")
    text = _extract(name, content)
    with tx() as conn:
        resume_id = profile_repo.insert_resume(
            conn, name=name, text=text, filename=name, origin="upload"
        )
        stored = profile_repo.get_resume(conn, resume_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="resume was not stored")
    return stored


@router.post("/resumes/{resume_id}/select")
def select_resume(resume_id: int) -> dict[str, Any]:
    with tx() as conn:
        if not profile_repo.select_resume(conn, resume_id):
            raise HTTPException(status_code=404, detail="no such resume")
        stored = profile_repo.get_resume(conn, resume_id)
    return stored or {}


@router.delete("/resumes/{resume_id}", status_code=204)
def delete_resume(resume_id: int) -> None:
    with tx() as conn:
        if not profile_repo.delete_resume(conn, resume_id):
            raise HTTPException(status_code=404, detail="no such resume")


def _extract(name: str, content: bytes) -> str:
    if name.lower().endswith(".pdf"):
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    return content.decode("utf-8", errors="replace").strip()
