from dataclasses import dataclass, field
from pathlib import Path
from fractions import Fraction
import uuid

import numpy as np

SAMPLE_RATE = 4000


@dataclass
class Clip:
    path: Path
    duration: float
    audio: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32), repr=False)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    fps: Fraction = Fraction(25, 1)
    width: int = 0
    height: int = 0
    channels: int = 0
    source_sample_rate: int = 48000
    audio_start: float = 0.0
    channel_used: int = 0
    offset: float | None = None
    score: float = 0.0
    status: str = "대기"
    included: bool = False
    warnings: list[str] = field(default_factory=list)
    features: np.ndarray | None = field(default=None, repr=False)
    fingerprint: dict = field(default_factory=dict)
    source_in: float = 0.0
    track: str = ""
    display_name: str = ""
    excluded: bool = False  # Explicit user exclusion, retained across reanalysis.
    sync_group: int = 0  # 0: unconfirmed; each positive value is an independent audio group.

    @property
    def name(self):
        return self.display_name or self.path.name

    @property
    def has_video(self):
        return self.width > 0 and self.height > 0


@dataclass(frozen=True)
class PairMatch:
    a: str
    b: str
    offset: float  # b's file start minus a's file start, in seconds
    score: float
    overlap: float
    drift_ms: float = 0.0
    jitter_ms: float = 0.0  # Deviations from a constant/linear offset; never silently corrected.


@dataclass
class SyncResult:
    placements: dict[str, float]
    scores: dict[str, float]
    matches: list[PairMatch]
    warnings: dict[str, list[str]] = field(default_factory=dict)
    group_ids: dict[str,int] = field(default_factory=dict)


class Cancelled(Exception):
    pass
