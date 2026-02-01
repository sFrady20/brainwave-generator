"""Episode data models."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EpisodeStatus(str, Enum):
    """Episode generation status."""

    PENDING = "pending"
    PLOT_GENERATED = "plot_generated"
    SCRIPT_GENERATED = "script_generated"
    BUILT = "built"
    FAILED = "failed"


class PlotBeat(BaseModel):
    """A single story beat in the episode plot."""

    name: str  # exposition, rising_action, climax, falling_action, resolution
    content: str

    class Config:
        frozen = True


class EpisodePlot(BaseModel):
    """Structured episode plot with title and beats."""

    title: str
    beats: list[PlotBeat]
    raw_text: str = ""

    @property
    def exposition(self) -> str | None:
        """Get exposition beat content."""
        return next((b.content for b in self.beats if b.name == "exposition"), None)

    @property
    def rising_action(self) -> str | None:
        """Get rising action beat content."""
        return next((b.content for b in self.beats if b.name == "rising_action"), None)

    @property
    def climax(self) -> str | None:
        """Get climax beat content."""
        return next((b.content for b in self.beats if b.name == "climax"), None)

    @property
    def falling_action(self) -> str | None:
        """Get falling action beat content."""
        return next((b.content for b in self.beats if b.name == "falling_action"), None)

    @property
    def resolution(self) -> str | None:
        """Get resolution beat content."""
        return next((b.content for b in self.beats if b.name == "resolution"), None)


class EpisodeMeta(BaseModel):
    """Episode metadata stored in meta.json."""

    id: UUID = Field(default_factory=uuid4)
    version: str = "1.0.0"
    status: EpisodeStatus = EpisodeStatus.PENDING
    topic: str | None = None
    title: str | None = None
    rating: int = 5
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: datetime | None = None
    build_mocked: bool = False
    model_used: str | None = None
    tts_provider: str | None = None
    generation_tokens: int | None = None
    scene_count: int | None = None
    dialog_count: int | None = None

    def model_dump_json_compatible(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        data = self.model_dump()
        data["id"] = str(data["id"])
        data["status"] = data["status"].value
        if data["created_at"]:
            data["created_at"] = data["created_at"].isoformat()
        if data["completed_at"]:
            data["completed_at"] = data["completed_at"].isoformat()
        return data


class Episode(BaseModel):
    """Complete episode data container."""

    meta: EpisodeMeta
    plot: EpisodePlot | None = None
    script_raw: str | None = None  # Raw WaveLang script text
    work_dir: Path | None = None

    @classmethod
    def new(cls, topic: str | None = None) -> "Episode":
        """Create a new episode with a fresh UUID."""
        meta = EpisodeMeta(topic=topic)
        return cls(meta=meta)

    @property
    def id(self) -> UUID:
        """Get episode UUID."""
        return self.meta.id

    @property
    def id_str(self) -> str:
        """Get episode UUID as string."""
        return str(self.meta.id)
