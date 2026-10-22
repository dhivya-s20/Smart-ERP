
"""
main.py - SMART ERP Certificate Service
FastAPI + Supabase + OCR + OpenAI AI Assistant

Run from the project root:
    python -m uvicorn app.main:app --reload --reload-dir app --port 8000

API docs:
    http://localhost:8000/docs
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import Client, create_client

# Load .env from the project root.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.ocr_service import (
    DOC_TYPES,
    extract_text,
    mask_sensitive,
    parse_document,
    validate_document,
)

from app.ai_routes import router as ai_router


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()

SUPABASE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or ""
).strip()

BUCKET = (
    os.getenv("SUPABASE_STORAGE_BUCKET")
    or os.getenv("SUPABASE_BUCKET")
    or "certificates"
).strip()

CERTIFICATE_ADMIN_USER_IDS = {
    value.strip()
    for value in os.getenv("ERP_CERTIFICATE_ADMIN_USER_IDS", "").split(",")
    if value.strip()
}

MAX_FILE_MB = 10

ALLOWED_EXT = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
}


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SMART ERP - Certificate OCR",
    version="1.2.0",
    description=(
        "Certificate OCR, Supabase storage, student records, "
        "verification, and AI Assistant API."
    ),
)

# Register AI Assistant endpoints.
app.include_router(ai_router)

configured_origins = os.getenv("FRONTEND_ORIGINS", "").strip()
frontend_origins = ["https://smart-erp-five-umber.vercel.app"]
frontend_origins.extend(
    origin.strip()
    for origin in configured_origins.split(",")
    if origin.strip()
)
if not configured_origins:
    frontend_origins.extend(
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

# Preserve order while removing duplicate origins.
frontend_origins = list(dict.fromkeys(frontend_origins))

if "*" in frontend_origins:
    raise RuntimeError("FRONTEND_ORIGINS must contain explicit origins, not '*'.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------------------------
# Supabase connection
# ---------------------------------------------------------------------------

_sb: Optional[Client] = None


def get_sb() -> Client:
    """Create and reuse the Supabase client."""

    global _sb

    if _sb is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Supabase configuration is missing. "
                    "Check SUPABASE_URL and SUPABASE_KEY "
                    "or SUPABASE_SERVICE_ROLE_KEY in .env."
                ),
            )

        try:
            _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not create the Supabase client. "
                    "Check backend configuration."
                ),
            )

    return _sb


def require_authenticated_user(
    authorization: Optional[str] = Header(default=None),
) -> Any:
    """Verify the caller's Supabase access token and return its Auth user."""

    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="A valid Supabase Bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        auth_result = get_sb().auth.get_user(token.strip())
        user = getattr(auth_result, "user", None)
        if not user or not getattr(user, "id", None):
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Unable to verify your session. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_certificate_admin(
    current_user: Any = Depends(require_authenticated_user),
) -> Any:
    """Limit service-role access to explicitly configured ERP administrators."""

    if str(current_user.id) not in CERTIFICATE_ADMIN_USER_IDS:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to access certificate records.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_cfg(doc_type: str) -> dict:
    """Get the configuration for a supported certificate type."""

    cfg = DOC_TYPES.get(doc_type)

    if not cfg:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown doc_type '{doc_type}'. See GET /doc-types.",
        )

    return cfg


def read_upload(file: UploadFile) -> bytes:
    """Read and validate an uploaded file."""

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed extensions: {sorted(ALLOWED_EXT)}"
            ),
        )

    content = file.file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty.",
        )

    if len(content) > MAX_FILE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_FILE_MB} MB limit.",
        )

    return content



def run_ocr(doc_type: str, content: bytes, filename: str):
    """Extract text and normalize parser output for certificate fields."""

    try:
        text = extract_text(content, filename)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="OCR failed. Check the file and OCR configuration.",
        )

    if not text or not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No readable text was found in this file.",
        )

    try:
        parsed = parse_document(doc_type, text)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="Certificate parsing failed. Check the OCR parser.",
        )

    # Some parsers return {"fields": {...}}, while others
    # may return the fields dictionary directly.
    if isinstance(parsed, dict) and isinstance(parsed.get("fields"), dict):
        fields = parsed["fields"]
    elif isinstance(parsed, dict):
        fields = parsed
    else:
        raise HTTPException(
            status_code=422,
            detail="The certificate parser returned an invalid result.",
        )

    return text, fields



def signed_url(
    path: Optional[str],
    expires: int = 3600,
) -> Optional[str]:
    """Create a temporary URL for a stored certificate."""

    if not path:
        return None

    try:
        result = get_sb().storage.from_(BUCKET).create_signed_url(
            path,
            expires,
        )

        return result.get("signedURL") or result.get("signedUrl")

    except Exception:
        return None


def known_names(student_id: int) -> list:
    """Get candidate names already saved for the student."""

    names = []

    for table in ("state_board_10th", "state_board_12th"):
        try:
            result = (
                get_sb()
                .table(table)
                .select("candidate_name")
                .eq("student_id", student_id)
                .execute()
            )

            rows = result.data or []

            names.extend(
                row["candidate_name"]
                for row in rows
                if row.get("candidate_name")
            )

        except Exception:
            # A missing table should not break OCR preview.
            continue

    return names


def _norm_name(value: str) -> str:
    """Normalize spaces and periods for name comparison."""

    return re.sub(r"[\s.]", "", value or "").upper()


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
def health():
    """Check whether the API is running."""

    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health/supabase", tags=["Health"])
def health_supabase(
    _current_user: Any = Depends(require_certificate_admin),
):
    """Check Supabase configuration, database access, and storage."""

    result = {
        "url_set": bool(SUPABASE_URL),
        "key_set": bool(SUPABASE_KEY),
        "bucket": BUCKET,
    }

    sb = get_sb()

    try:
        (
            sb.table("student_identification")
            .select("student_id")
            .limit(1)
            .execute()
        )
        result["database"] = "ok"

    except Exception:
        result["database"] = "error"

    try:
        sb.storage.from_(BUCKET).list()
        result["storage"] = "ok"

    except Exception:
        result["storage"] = "error"

    return result


# ---------------------------------------------------------------------------
# Certificate types
# ---------------------------------------------------------------------------

@app.get("/doc-types", tags=["Certificates"])
def doc_types(
    _current_user: Any = Depends(require_authenticated_user),
):
    """Return supported document types and their table configurations."""

    return {
        key: {
            "table": value["table"],
            "has_verification": value["verification"],
        }
        for key, value in DOC_TYPES.items()
    }


# ---------------------------------------------------------------------------
# OCR preview - does not save anything
# ---------------------------------------------------------------------------

@app.post("/extract/{doc_type}", tags=["OCR"])
def extract_only(
    doc_type: str,
    file: UploadFile = File(...),
    student_id: Optional[int] = Form(None),
    _current_user: Any = Depends(require_certificate_admin),
):
    """Preview OCR and parsed fields without saving the certificate."""

    get_cfg(doc_type)

    content = read_upload(file)

    text, fields = run_ocr(
        doc_type,
        content,
        file.filename or "",
    )

    warnings = validate_document(
        doc_type,
        fields,
        text,
    )

    candidate_name = fields.get("candidate_name")

    if student_id and candidate_name:
        for saved_name in known_names(student_id):
            if (
                saved_name != candidate_name
                and _norm_name(saved_name) == _norm_name(candidate_name)
            ):
                warnings.append(
                    f"Name spelling differs from the saved record: "
                    f"'{saved_name}' (this sheet reads '{candidate_name}')."
                )
                break

    return {
        "doc_type": doc_type,
        "fields": fields,
        "warnings": warnings,
        "extracted_text": mask_sensitive(text),
    }


# ---------------------------------------------------------------------------
# Upload certificate - stores file and parsed data in Supabase
# ---------------------------------------------------------------------------

@app.post("/upload/{doc_type}", tags=["Certificates"])
def upload_certificate(
    doc_type: str,
    student_id: int = Form(...),
    file: UploadFile = File(...),
    overrides: Optional[str] = Form(
        None,
        description="JSON containing corrected certificate fields.",
    ),
    _current_user: Any = Depends(require_certificate_admin),
):
    """
    Validate the student, run OCR, upload the file to Supabase Storage,
    and insert parsed fields into the configured document table.
    """

    cfg = get_cfg(doc_type)
    sb = get_sb()

    # Verify that the student exists.
    try:
        student_result = (
            sb.table("student_identification")
            .select("student_id")
            .eq("student_id", student_id)
            .limit(1)
            .execute()
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not check the student record in Supabase.",
        )

    if not student_result.data:
        raise HTTPException(
            status_code=404,
            detail=(
                f"student_id {student_id} was not found "
                "in student_identification."
            ),
        )

    content = read_upload(file)

    text, fields = run_ocr(
        doc_type,
        content,
        file.filename or "",
    )

    # Apply manually corrected fields if provided.
    if overrides:
        try:
            manual_fields = json.loads(overrides)

        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="overrides must contain valid JSON.",
            )

        if not isinstance(manual_fields, dict):
            raise HTTPException(
                status_code=400,
                detail="overrides must be a JSON object.",
            )

        unknown_fields = [
            key for key in manual_fields
            if key not in fields
        ]

        if unknown_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown fields in overrides: {unknown_fields}",
            )

        fields.update(manual_fields)

    filename = file.filename or "certificate"
    ext = os.path.splitext(filename)[1].lower()

    storage_path = (
        f"{doc_type}/{student_id}/{uuid.uuid4().hex}{ext}"
    )

    # Upload original certificate to Supabase Storage.
    try:
        sb.storage.from_(BUCKET).upload(
            storage_path,
            content,
            {
                "content-type": (
                    file.content_type or "application/octet-stream"
                ),
                "upsert": "true",
            },
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Certificate file upload to Supabase Storage failed.",
        )

    # Prepare database row.
    row = {
        key: value
        for key, value in fields.items()
        if value is not None
    }

    row["student_id"] = student_id
    row["certificate_file_path"] = storage_path

    if cfg["extracted_text"]:
        row["extracted_text"] = mask_sensitive(text)

    # Insert parsed data into the document table.
    try:
        result = (
            sb.table(cfg["table"])
            .insert(row)
            .execute()
        )

    except Exception:
        try:
            sb.storage.from_(BUCKET).remove([storage_path])
        except Exception:
            pass

        raise HTTPException(
            status_code=400,
            detail=(
                "Database insert failed. Check the target table "
                "and column names."
            ),
        )

    saved_record = result.data[0] if result.data else row

    return {
        "saved": True,
        "doc_type": doc_type,
        "record": saved_record,
    }


# ---------------------------------------------------------------------------
# List ALL certificates - NEW ENDPOINT FOR MY CERTIFICATES PAGE
# ---------------------------------------------------------------------------

@app.get("/certificates/", tags=["Certificates"])
def list_all_certificates(
    _current_user: Any = Depends(require_certificate_admin),
):
    """
    Return certificates from all document tables configured in DOC_TYPES.

    Response format:
    {
        "count": 1,
        "items": [
            {
                "student_id": 1,
                "doc_type": "community_certificate",
                "file_url": "..."
            }
        ]
    }
    """

    sb = get_sb()
    all_items = []

    for doc_type, cfg in DOC_TYPES.items():
        table_name = cfg["table"]

        try:
            result = (
                sb.table(table_name)
                .select("*")
                .execute()
            )

            rows = result.data or []

            for row in rows:
                item = dict(row)

                # Identify which certificate type this row belongs to.
                item["doc_type"] = doc_type

                # Provide a temporary URL for the uploaded file.
                item["file_url"] = signed_url(
                    item.get("certificate_file_path")
                )

                all_items.append(item)

        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Failed to retrieve certificates from "
                    f"table '{table_name}': {str(exc)}"
                ),
            )

    # Sort newest first if created_at is available.
    all_items.sort(
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )

    return {
        "count": len(all_items),
        "items": all_items,
    }


# ---------------------------------------------------------------------------
# List certificates for a specific student and document type
# ---------------------------------------------------------------------------

@app.get(
    "/certificates/{doc_type}/{student_id}",
    tags=["Certificates"],
)
def list_certificates(
    doc_type: str,
    student_id: int,
    _current_user: Any = Depends(require_certificate_admin),
):
    """Return saved certificates for the specified student."""

    cfg = get_cfg(doc_type)

    try:
        result = (
            get_sb()
            .table(cfg["table"])
            .select("*")
            .eq("student_id", student_id)
            .order("created_at", desc=True)
            .execute()
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve certificates from Supabase.",
        )

    rows = result.data or []

    for row in rows:
        row["file_url"] = signed_url(
            row.get("certificate_file_path")
        )

    return {
        "count": len(rows),
        "items": rows,
    }


# ---------------------------------------------------------------------------
# Certificate verification
# ---------------------------------------------------------------------------

class VerifyBody(BaseModel):
    status: str = "verified"


@app.patch(
    "/verify/{doc_type}/{record_id}",
    tags=["Verification"],
)
def verify_certificate(
    doc_type: str,
    record_id: int,
    body: VerifyBody,
    current_user: Any = Depends(require_certificate_admin),
):
    """Update the verification status of a certificate."""

    cfg = get_cfg(doc_type)

    if not cfg["verification"]:
        raise HTTPException(
            status_code=400,
            detail=f"'{doc_type}' table has no verification columns.",
        )

    if body.status not in {"verified", "rejected", "pending"}:
        raise HTTPException(
            status_code=400,
            detail="status must be verified, rejected, or pending.",
        )

    try:
        result = (
            get_sb()
            .table(cfg["table"])
            .update(
                {
                    "verification_status": body.status,
                    "verified_by": str(current_user.id),
                    "verified_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }
            )
            .eq("id", record_id)
            .execute()
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Certificate verification update failed.",
        )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Certificate record was not found.",
        )

    return {
        "updated": True,
        "record": result.data[0],
    }


# ---------------------------------------------------------------------------
# Delete certificate
# ---------------------------------------------------------------------------

@app.delete(
    "/certificates/{doc_type}/{record_id}",
    tags=["Certificates"],
)
def delete_certificate(
    doc_type: str,
    record_id: int,
    _current_user: Any = Depends(require_certificate_admin),
):
    """Delete a certificate record and attempt to remove its stored file."""

    cfg = get_cfg(doc_type)
    sb = get_sb()

    try:
        found = (
            sb.table(cfg["table"])
            .select("certificate_file_path")
            .eq("id", record_id)
            .execute()
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not find the certificate record.",
        )

    if not found.data:
        raise HTTPException(
            status_code=404,
            detail="Certificate record was not found.",
        )

    storage_path = found.data[0].get("certificate_file_path")

    try:
        (
            sb.table(cfg["table"])
            .delete()
            .eq("id", record_id)
            .execute()
        )

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not delete the certificate record.",
        )

    if storage_path:
        try:
            sb.storage.from_(BUCKET).remove([storage_path])
        except Exception:
            # The database row is already deleted.
            pass

    return {
        "deleted": True,
        "record_id": record_id,
    }
