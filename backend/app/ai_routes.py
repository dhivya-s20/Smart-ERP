
# app/ai_routes.py
# SMART ERP - AI Assistant + Supabase Student Certificate Lookup

import os
import re
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

router = APIRouter(prefix="/api/ai", tags=["AI Chat"])

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat",
).strip()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2").strip()

STUDENT_TABLE = "student_identification"

ALLOWED_LOOKUP_USER_IDS = {
    value.strip()
    for value in os.getenv(
        "ERP_LOOKUP_ALLOWED_USER_IDS", ""
    ).split(",")
    if value.strip()
}

# --------------------------------------------------
# REQUEST MODEL
# --------------------------------------------------

class ChatRequest(BaseModel):
    message: str = ""
    prompt: str = ""
    history: list = Field(default_factory=list)


# --------------------------------------------------
# SHARED SUPABASE CLIENT
# Reuses get_sb() from your existing app/main.py.
# --------------------------------------------------

def get_supabase_client():
    from app.main import get_sb
    return get_sb()


# --------------------------------------------------
# STANDARD RESPONSE
# Keep all four response keys for frontend compatibility.
# --------------------------------------------------

def make_response(reply: str, source: str = "assistant"):
    return {
        "reply": reply,
        "response": reply,
        "answer": reply,
        "source": source,
    }


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

def authorize_student_lookup(authorization: Optional[str]):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Please sign in before searching student records.",
        )

    token = authorization.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing access token.",
        )

    if not ALLOWED_LOOKUP_USER_IDS:
        raise HTTPException(
            status_code=403,
            detail="Student lookup is not configured for authorized users.",
        )

    # Use the same server-side token verification and safe error classification
    # as the certificate routes.
    from app.main import verify_supabase_access_token

    user = verify_supabase_access_token(token)
    user_id = str(user.id)

    if user_id not in ALLOWED_LOOKUP_USER_IDS:
        raise HTTPException(
            status_code=403,
            detail="You are not authorized to search student records.",
        )

    return user_id


# --------------------------------------------------
# ALLOWED COLUMNS FOR EACH CERTIFICATE TABLE
#
# Sensitive OCR text, addresses, file paths and full
# identity information are deliberately not returned.
#
# Confirm these column names against your database.
# --------------------------------------------------

CERTIFICATE_TABLES = {
    "state_board_10th": [
        "id",
        "student_id",
        "candidate_name",
        "register_number",
        "permanent_register_number",
        "created_at",
    ],
    "state_board_12th": [
        "id",
        "student_id",
        "candidate_name",
        "register_number",
        "permanent_register_number",
        "created_at",
    ],
    "cbse_10th_marksheet": [
        "id",
        "student_id",
        "candidate_name",
        "roll_number",
        "created_at",
    ],
    "cbse_12th_marksheet": [
        "id",
        "student_id",
        "candidate_name",
        "roll_number",
        "created_at",
    ],
    "state_board_10th_tc": [
        "id",
        "student_id",
        "student_name",
        "tc_number",
        "admission_number",
        "verification_status",
        "created_at",
    ],
    "state_board_12th_tc": [
        "id",
        "student_id",
        "student_name",
        "tc_number",
        "admission_number",
        "verification_status",
        "created_at",
    ],
    "cbse_10th_tc": [
        "id",
        "student_id",
        "student_name",
        "tc_number",
        "admission_number",
        "created_at",
    ],
    "cbse_12th_tc": [
        "id",
        "student_id",
        "student_name",
        "tc_number",
        "admission_number",
        "created_at",
    ],
    "birth_certificate": [
        "id",
        "student_id",
        "student_name",
        "certificate_number",
        "issue_date",
        "created_at",
    ],
    "aadhaar_card": [
        "id",
        "student_id",
        "name_on_card",
        "aadhaar_last_four",
        "created_at",
    ],
    "community_certificate": [
        "id",
        "student_id",
        "candidate_name",
        "certificate_number",
        "community_name",
        "caste_name",
        "issue_date",
        "created_at",
    ],
    "income_certificate": [
        "id",
        "student_id",
        "candidate_name",
        "certificate_number",
        "occupation",
        "issue_date",
        "created_at",
    ],
    "nativity_certificate": [
        "id",
        "student_id",
        "candidate_name",
        "certificate_number",
        "issue_date",
        "created_at",
    ],
    "degree_certificate": [
        "id",
        "student_id",
        "candidate_name",
        "register_number",
        "certificate_number",
        "college_name",
        "university_name",
        "degree_name",
        "department",
        "graduation_year",
        "classification",
        "result",
        "created_at",
    ],
    "diploma_certificate": [
        "id",
        "student_id",
        "candidate_name",
        "register_number",
        "certificate_number",
        "college_name",
        "course_name",
        "department",
        "completion_year",
        "classification",
        "result",
        "created_at",
    ],
    "diploma_semester_marksheet": [
        "id",
        "student_id",
        "candidate_name",
        "register_number",
        "college_name",
        "course_name",
        "department",
        "semester",
        "exam_month",
        "exam_year",
        "total_marks",
        "percentage",
        "result",
        "created_at",
    ],
}


# --------------------------------------------------
# CENTRAL STUDENT SEARCH
# Central table columns are based on your supplied schema.
# --------------------------------------------------

def find_students(search_value: str, search_type: str):
    sb = get_supabase_client()

    query = (
        sb.table(STUDENT_TABLE)
        .select(
            "student_id,student_name,admission_number,"
            "college_name,department,course_name,admission_year"
        )
    )

    if search_type == "admission":
        query = query.eq("admission_number", search_value)
    else:
        # Escape wildcard characters in the supplied search.
        escaped = (
            search_value
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        query = query.ilike("student_name", f"%{escaped}%")

    result = query.limit(10).execute()
    return result.data or []


# --------------------------------------------------
# CERTIFICATE LOOKUP
# Every table is queried through its student_id foreign key.
# --------------------------------------------------

def lookup_certificates(student_id: int):
    sb = get_supabase_client()

    found = {}
    failed_tables = []

    for table_name, columns in CERTIFICATE_TABLES.items():
        try:
            result = (
                sb.table(table_name)
                .select(",".join(columns))
                .eq("student_id", student_id)
                .limit(20)
                .execute()
            )

            if result.data:
                found[table_name] = result.data

        except Exception:
            logger.exception(
                "Certificate lookup failed for table %s",
                table_name,
            )
            failed_tables.append(table_name)

    return found, failed_tables


# --------------------------------------------------
# LOOKUP COMMAND PARSER
# --------------------------------------------------

def parse_lookup(message: str):
    text = message.strip()
    lowered = text.lower()

    commands = [
        ("find student by admission number:", "admission"),
        ("search student by admission number:", "admission"),
        ("find student by admission:", "admission"),
        ("find student by name:", "name"),
        ("search student by name:", "name"),
    ]

    for prefix, search_type in commands:
        if lowered.startswith(prefix):
            value = text[len(prefix):].strip()

            if value:
                return search_type, value

    return None, None


# --------------------------------------------------
# FORMAT STUDENT LOOKUP RESULT
# --------------------------------------------------

def format_student(student: dict, certificates: dict, failures: list):
    lines = [
        "Student Details",
        "---------------",
        f"Student ID: {student.get('student_id')}",
        f"Name: {student.get('student_name')}",
        f"Admission Number: {student.get('admission_number')}",
        f"College: {student.get('college_name')}",
        f"Department: {student.get('department') or 'Not available'}",
        f"Course: {student.get('course_name') or 'Not available'}",
        f"Admission Year: {student.get('admission_year') or 'Not available'}",
    ]

    total = sum(len(records) for records in certificates.values())

    lines.extend([
        "",
        f"Certificate records found: {total}",
    ])

    if certificates:
        lines.append("")

        for table_name, records in certificates.items():
            lines.append(
                f"{table_name.replace('_', ' ').title()} ({len(records)})"
            )

            for record in records:
                details = []

                for key, value in record.items():
                    if key in {"id", "student_id", "created_at"}:
                        continue

                    if value is not None:
                        label = key.replace("_", " ").title()
                        details.append(f"{label}: {value}")

                if details:
                    lines.append("  - " + " | ".join(details))

            lines.append("")

    if not certificates and not failures:
        lines.append("No linked certificate records were found.")

    if failures:
        lines.append(
            "Some tables could not be checked. Please review backend logs."
        )

    return "\n".join(lines)


# --------------------------------------------------
# OLLAMA GENERAL CHAT
# --------------------------------------------------

async def ask_ollama(message: str, history: list):
    messages = [
        {
            "role": "system",
            "content": (
                "You are the SMART ERP assistant. Explain certificate "
                "management, OCR, student records, and application features. "
                "Never invent database records or claim a database search "
                "succeeded unless its results were actually retrieved. "
                "For private student records, use the authenticated lookup."
            ),
        }
    ]

    for item in history[-10:]:
        if not isinstance(item, dict):
            continue

        role = item.get("role")
        content = item.get("content", item.get("message", ""))

        if (
            role in {"user", "assistant"}
            and isinstance(content, str)
            and content.strip()
        ):
            messages.append({
                "role": role,
                "content": content[:4000],
            })

    messages.append({
        "role": "user",
        "content": message[:4000],
    })

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "messages": messages,
                    "stream": False,
                },
            )
            response.raise_for_status()
            data = response.json()

        return data.get("message", {}).get(
            "content",
            "Sorry, I could not generate a response.",
        ).strip()

    except httpx.ConnectError:
        logger.warning("Ollama connection failed.")
        return (
            "Ollama is not running. Start Ollama and check that "
            f"the '{OLLAMA_MODEL}' model is installed."
        )

    except Exception:
        logger.exception("Ollama request failed.")
        return "The AI service is temporarily unavailable. Please try again."


# --------------------------------------------------
# CHAT ENDPOINT
# POST /api/ai/chat
# --------------------------------------------------

@router.post("/chat")
async def chat(
    request: ChatRequest,
    authorization: Optional[str] = Header(default=None),
):
    message = (request.message or request.prompt).strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Please enter a message.",
        )

    search_type, search_value = parse_lookup(message)

    # Student record lookup
    if search_type:
        authorize_student_lookup(authorization)

        try:
            students = find_students(search_value, search_type)

        except HTTPException:
            raise

        except Exception:
            logger.exception("Central student search failed.")
            raise HTTPException(
                status_code=502,
                detail="Student search failed. Check the backend logs.",
            )

        if not students:
            return make_response(
                "No matching student was found in student_identification.",
                "supabase",
            )

        if len(students) > 1:
            choices = [
                (
                    f"- {student.get('student_name')} "
                    f"(Admission number: {student.get('admission_number')})"
                )
                for student in students
            ]

            return make_response(
                "Multiple students matched. Search using the exact "
                "admission number:\n" + "\n".join(choices),
                "supabase",
            )

        student = students[0]

        try:
            certificates, failures = lookup_certificates(
                int(student["student_id"])
            )
        except Exception:
            logger.exception("Certificate lookup failed.")
            raise HTTPException(
                status_code=502,
                detail="Could not retrieve certificate records.",
            )

        return make_response(
            format_student(student, certificates, failures),
            "supabase",
        )

    # General assistant response
    reply = await ask_ollama(message, request.history)
    return make_response(reply, "ollama")
