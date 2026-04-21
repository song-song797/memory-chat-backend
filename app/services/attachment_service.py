import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import MAX_ATTACHMENT_SIZE_BYTES, MAX_ATTACHMENTS_PER_MESSAGE, UPLOADS_DIR
from ..models import Attachment


def _normalize_name(name: str | None) -> str:
    if not name:
        return "attachment"

    candidate = Path(name).name.strip()
    return candidate or "attachment"


def _infer_mime_type(upload: UploadFile, filename: str) -> str:
    if upload.content_type:
        return upload.content_type

    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _infer_kind(mime_type: str) -> str:
    return "image" if mime_type.startswith("image/") else "file"


def get_attachment_path(attachment: Attachment) -> Path:
    return UPLOADS_DIR / attachment.stored_name


async def save_attachments(
    db: Session,
    message_id: str,
    uploads: list[UploadFile],
) -> list[Attachment]:
    if not uploads:
        return []

    if len(uploads) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_ATTACHMENTS_PER_MESSAGE} attachments are allowed per message",
        )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    attachments: list[Attachment] = []
    written_paths: list[Path] = []

    try:
        for upload in uploads:
            filename = _normalize_name(upload.filename)
            payload = await upload.read()

            if not payload:
                raise HTTPException(status_code=400, detail=f"`{filename}` is empty")

            if len(payload) > MAX_ATTACHMENT_SIZE_BYTES:
                limit_mb = MAX_ATTACHMENT_SIZE_BYTES // (1024 * 1024)
                raise HTTPException(
                    status_code=400,
                    detail=f"`{filename}` exceeds the {limit_mb} MB size limit",
                )

            suffix = Path(filename).suffix
            stored_name = f"{uuid.uuid4().hex}{suffix}"
            file_path = UPLOADS_DIR / stored_name
            file_path.write_bytes(payload)
            written_paths.append(file_path)
            mime_type = _infer_mime_type(upload, filename)

            attachment = Attachment(
                message_id=message_id,
                name=filename,
                stored_name=stored_name,
                mime_type=mime_type,
                kind=_infer_kind(mime_type),
                size_bytes=len(payload),
            )
            db.add(attachment)
            attachments.append(attachment)
    except Exception:
        for path in written_paths:
            if path.exists():
                path.unlink()
        raise

    db.commit()

    for attachment in attachments:
        db.refresh(attachment)

    return attachments
