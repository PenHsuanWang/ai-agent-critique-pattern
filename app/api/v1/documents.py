"""Document management API — upload and delete local documents.

Identical in behaviour to the MVP's documents.py.
Endpoints:
  GET    /api/v1/documents              — list all documents
  POST   /api/v1/documents              — upload a new document (no overwrite)
  DELETE /api/v1/documents/{filename}   — delete an existing document
"""

import logging
import re
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.schemas.documents import DeleteResponse, ListResponse, UploadResponse
from app.services.tools.common_tools import DOCS_DIR

router = APIRouter()
logger = logging.getLogger(__name__)

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-][a-zA-Z0-9_\-. ]*$")
_ALLOWED_EXTENSIONS = {".txt", ".md", ".csv"}


def _validate_filename(filename: str) -> str:
    safe_name = PurePosixPath(filename).name
    if not safe_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename must not be empty.",
        )
    if not _SAFE_FILENAME_RE.match(safe_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Filename '{safe_name}' contains invalid characters.",
        )
    ext = Path(safe_name).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Extension '{ext}' is not supported. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )
    return safe_name


def _resolve_safe(filename: str) -> Path:
    target = (DOCS_DIR / filename).resolve()
    if DOCS_DIR not in target.parents and target != DOCS_DIR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access denied: path escapes the documents directory.",
        )
    return target


@router.get("", response_model=ListResponse, summary="List all available documents")
async def list_documents() -> ListResponse:
    files = sorted(f.name for f in DOCS_DIR.iterdir() if f.is_file())
    return ListResponse(documents=files, total=len(files))


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new document",
)
async def upload_document(file: UploadFile) -> UploadResponse:
    safe_name = _validate_filename(file.filename or "")
    target = _resolve_safe(safe_name)
    if target.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document '{safe_name}' already exists. Delete it first.",
        )
    try:
        content = await file.read()
        content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be valid UTF-8 encoded text.",
        )
    target.write_bytes(content)
    logger.info("Document uploaded: '%s' (%d bytes)", safe_name, len(content))
    return UploadResponse(filename=safe_name, size_bytes=len(content))


@router.delete(
    "/{filename}",
    response_model=DeleteResponse,
    summary="Delete a document",
)
async def delete_document(filename: str) -> DeleteResponse:
    safe_name = _validate_filename(filename)
    target = _resolve_safe(safe_name)
    if not target.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{safe_name}' not found.",
        )
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{safe_name}' is not a file.",
        )
    target.unlink()
    logger.info("Document deleted: '%s'", safe_name)
    return DeleteResponse(filename=safe_name)
