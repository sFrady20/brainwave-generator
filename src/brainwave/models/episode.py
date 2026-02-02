"""Episode data models."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EpisodeStatus(str, Enum):
    """Episode generation status - state machine for the pipeline."""

    CREATED = "created"      # Initial state
    OUTLINED = "outlined"    # Outline generated
    SCRIPTED = "scripted"    # Full script generated
    BUILT = "built"          # TTS audio generated
    COMPLETED = "completed"  # Uploaded to cloud
    FAILED = "failed"        # Error state

    # Legacy statuses for backwards compatibility
    PENDING = "pending"
    PLOT_GENERATED = "plot_generated"
    SCRIPT_GENERATED = "script_generated"


class PipelineStep(str, Enum):
    """Pipeline steps that can be executed."""

    OUTLINE = "outline"
    SCRIPT = "script"
    BUILD = "build"
    COMPLETE = "complete"


class PlotBeat(BaseModel):
    """A single story beat in the episode plot."""

    name: str  # exposition, rising_action, climax, falling_action, resolution
    content: str

    class Config:
        frozen = True


class SceneBeat(BaseModel):
    """A scene beat in the outline - describes what happens without dialog."""

    scene_num: int
    shot_id: int
    characters: list[str]
    setup: str
    beat: str
    lands: str


class EpisodeOutline(BaseModel):
    """Detailed episode outline for script generation."""

    title: str
    premise: str  # The comedic engine of the episode
    theme: str | None = None  # What it's actually about underneath
    scenes: list[SceneBeat] = Field(default_factory=list)
    callbacks: list[str] = Field(default_factory=list)  # Jokes that pay off later
    ending: str | None = None
    raw_text: str = ""


class EpisodePlot(BaseModel):
    """Structured episode plot with title and beats (legacy format)."""

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
    version: str = "2.0.0"
    status: EpisodeStatus = EpisodeStatus.CREATED
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

    # Pipeline tracking
    steps_completed: list[str] = Field(default_factory=list)
    current_step: str | None = None

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

    def mark_step_completed(self, step: PipelineStep) -> None:
        """Mark a pipeline step as completed."""
        if step.value not in self.steps_completed:
            self.steps_completed.append(step.value)

    def get_next_step(self) -> PipelineStep | None:
        """Get the next step to execute based on status."""
        status_to_next: dict[EpisodeStatus, PipelineStep | None] = {
            EpisodeStatus.CREATED: PipelineStep.OUTLINE,
            EpisodeStatus.OUTLINED: PipelineStep.SCRIPT,
            EpisodeStatus.SCRIPTED: PipelineStep.BUILD,
            EpisodeStatus.BUILT: PipelineStep.COMPLETE,
            EpisodeStatus.COMPLETED: None,
            EpisodeStatus.FAILED: None,
            # Legacy mappings
            EpisodeStatus.PENDING: PipelineStep.OUTLINE,
            EpisodeStatus.PLOT_GENERATED: PipelineStep.SCRIPT,
            EpisodeStatus.SCRIPT_GENERATED: PipelineStep.BUILD,
        }
        return status_to_next.get(self.status)


class Episode(BaseModel):
    """Complete episode data container."""

    meta: EpisodeMeta
    outline: EpisodeOutline | None = None  # New detailed outline
    plot: EpisodePlot | None = None  # Legacy plot format
    script_raw: str | None = None  # Raw WaveLang script text
    work_dir: Path | None = None

    class Config:
        arbitrary_types_allowed = True

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

    @property
    def title(self) -> str:
        """Get episode title from outline, plot, or meta."""
        if self.outline:
            return self.outline.title
        if self.plot:
            return self.plot.title
        return self.meta.title or "Untitled Episode"

    def is_incomplete(self) -> bool:
        """Check if episode is still in progress."""
        return self.meta.status not in (EpisodeStatus.COMPLETED, EpisodeStatus.FAILED)

    def can_resume(self) -> bool:
        """Check if episode can be resumed."""
        return self.is_incomplete() and self.meta.status != EpisodeStatus.FAILED
