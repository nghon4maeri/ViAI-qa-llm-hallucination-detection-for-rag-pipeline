# backend/app/modules/projects/service.py
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.project import ProjectModel


def ensure_default_project(db: Session) -> ProjectModel:
    """The one place that provisions the default workspace; audits, batches, API keys and startup use it."""
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
