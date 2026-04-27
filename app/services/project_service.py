from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Project


def trim_project_name(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Project name cannot be empty")
    return trimmed


def get_user_project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
