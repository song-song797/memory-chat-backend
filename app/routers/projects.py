from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Project, User, _utcnow
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate
from ..services.auth_service import get_current_user
from ..services.project_service import get_user_project, trim_project_name

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Project).where(Project.user_id == current_user.id)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    stmt = stmt.order_by(Project.is_default.desc(), Project.updated_at.desc())
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        user_id=current_user.id,
        name=trim_project_name(body.name),
        description=body.description.strip() if body.description else None,
        default_model=body.default_model,
        default_reasoning_level=body.default_reasoning_level,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_user_project(db, current_user.id, project_id)
    if (
        body.name is None
        and body.description is None
        and body.default_model is None
        and body.default_reasoning_level is None
        and body.archived is None
    ):
        raise HTTPException(status_code=400, detail="No project changes provided")

    if body.name is not None:
        project.name = trim_project_name(body.name)
    if body.description is not None:
        project.description = body.description.strip() or None
    if body.default_model is not None:
        project.default_model = body.default_model
    if body.default_reasoning_level is not None:
        project.default_reasoning_level = body.default_reasoning_level
    if body.archived is not None:
        project.archived_at = _utcnow() if body.archived else None

    db.commit()
    db.refresh(project)
    return project
