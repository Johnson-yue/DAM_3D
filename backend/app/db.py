from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    original_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    ext: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="copied")
    preview_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    glb_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    tag_status: Mapped[str] = mapped_column(String(32), default="none")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tags: Mapped[list["Tag"]] = relationship(back_populates="asset", cascade="all, delete-orphan")
    views: Mapped[list["ViewEmbedding"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="user")  # user | auto

    asset: Mapped["Asset"] = relationship(back_populates="tags")


class ViewEmbedding(Base):
    __tablename__ = "view_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    view_id: Mapped[str] = mapped_column(String(64), nullable=False)
    image_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    faiss_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)

    asset: Mapped["Asset"] = relationship(back_populates="views")


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # rect|text|arrow
    geometry_json: Mapped[str] = mapped_column(Text, nullable=False)
    camera_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    asset: Mapped["Asset"] = relationship(back_populates="annotations")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


_engine = None
SessionLocal = None


def init_db():
    global _engine, SessionLocal
    settings = get_settings()
    settings.library_root.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{settings.db_path.as_posix()}"
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(_engine)
    return _engine


def get_db():
    if SessionLocal is None:
        init_db()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
