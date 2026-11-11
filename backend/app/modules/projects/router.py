# backend/app/modules/projects/router.py
import re
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.config import settings
from backend.app.models.project import ProjectModel
from backend.app.modules.projects.schemas import ProjectCreateRequest, ProjectResponse

router = APIRouter(prefix="/projects", tags=["Projects"])


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def ensure_default_project(db: Session) -> ProjectModel:
    stmt = select(ProjectModel).where(ProjectModel.is_default == True).limit(1)
    project = db.execute(stmt).scalar_one_or_none()
    if not project:
        project = ProjectModel(
            name=settings.DEFAULT_PROJECT_NAME,
            slug=settings.DEFAULT_PROJECT_SLUG,
            description="System default workspace for evaluations",
            is_default=True
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    return project


@router.get("", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    ensure_default_project(db)
    stmt = select(ProjectModel).order_by(ProjectModel.created_at.asc())
    return db.execute(stmt).scalars().all()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(request: ProjectCreateRequest, db: Session = Depends(get_db)):
    base_slug = slugify(request.name) or "project"
    slug = base_slug
    counter = 1

    # Ensure unique slug
    while db.execute(select(ProjectModel).where(ProjectModel.slug == slug)).scalar_one_or_none():
        slug = f"{base_slug}-{counter}"
        counter += 1

    project = ProjectModel(
        name=request.name,
        slug=slug,
        description=request.description,
        is_default=False
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project
