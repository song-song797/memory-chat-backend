from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Attachment, User
from ..services.attachment_service import get_attachment_path
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.get("/{attachment_id}/content")
def get_attachment_content(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    attachment = db.get(Attachment, attachment_id)
    if (
        not attachment
        or not attachment.message
        or not attachment.message.conversation
        or attachment.message.conversation.user_id != current_user.id
    ):
        raise HTTPException(status_code=404, detail="Attachment not found")

    path = get_attachment_path(attachment)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file not found")

    return FileResponse(
        path,
        media_type=attachment.mime_type,
        filename=attachment.name,
    )
