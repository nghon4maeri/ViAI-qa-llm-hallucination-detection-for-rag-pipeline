# applications/rag-demo/rag_demo/store.py
"""Passage store in Postgres (or SQLite locally). A pgvector `embedding` column can be added later."""
import os
from typing import List

from sqlalchemy import Column, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


class Passage(Base):
    __tablename__ = "rag_passages"

    id = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False, unique=True)
    title = Column(String(500))
    topic = Column(String(50))
    source_url = Column(String(1000))


def engine_from_env(url: str = None):
    return create_engine(url or os.getenv("RAG_DATABASE_URL", "sqlite:///artifacts/local/rag_demo.db"))


def ingest_vimedaqa(engine, parquet_paths: List[str]) -> int:
    """Load unique ViMedAQA passages; re-running skips texts already stored."""
    import pandas as pd

    topics = {0: "body-part", 1: "disease", 2: "drug", 3: "medicine"}
    df = pd.concat([pd.read_parquet(p) for p in parquet_paths]).drop_duplicates("context")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        existing = set(s.scalars(select(Passage.text)))
        new = [
            Passage(text=r.context, title=r.title, topic=topics.get(int(r.topic), str(r.topic)), source_url=r.article_url)
            for r in df.itertuples(index=False) if r.context not in existing
        ]
        s.add_all(new)
        s.commit()
    return len(new)


def load_passages(engine) -> List[Passage]:
    with Session(engine) as s:
        return list(s.scalars(select(Passage).order_by(Passage.id)))
