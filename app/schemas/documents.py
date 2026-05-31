"""Pydantic schemas for the document management API (identical to MVP)."""

from pydantic import BaseModel, Field


class UploadResponse(BaseModel):
    filename: str = Field(..., description="Name of the uploaded file.")
    size_bytes: int = Field(..., description="Size of the uploaded file in bytes.")
    status: str = Field(default="uploaded")


class DeleteResponse(BaseModel):
    filename: str = Field(..., description="Name of the deleted file.")
    status: str = Field(default="deleted")


class ListResponse(BaseModel):
    documents: list[str] = Field(..., description="Sorted list of available document filenames.")
    total: int = Field(..., description="Total number of documents.")
