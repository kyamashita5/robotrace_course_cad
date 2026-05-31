from __future__ import annotations

from dataclasses import dataclass, field

from .course_model import Turn
from .geometry import Vec2


@dataclass(frozen=True)
class TangentSegment:
    from_circle_id: int
    to_circle_id: int
    p_from: Vec2
    p_to: Vec2
    kind: str
    choice: int

    @property
    def length(self) -> float:
        return self.p_from.distance_to(self.p_to)


@dataclass(frozen=True)
class ArcSegment:
    circle_id: int
    center: Vec2
    radius: float
    p_start: Vec2
    p_end: Vec2
    turn: Turn
    angle_rad: float
    length: float


@dataclass(frozen=True)
class CornerMarker:
    boundary_index: int
    point: Vec2
    center: Vec2
    tangent_angle_deg: float
    normal_angle_deg: float
    long_side_cm: float = 4.0
    short_side_cm: float = 1.9


@dataclass(frozen=True)
class StartGoalSegment:
    center: Vec2
    p_start: Vec2
    p_end: Vec2
    tangent_angle_deg: float
    length: float


@dataclass(frozen=True)
class StartGoalMarker:
    marker_index: int
    point: Vec2
    center: Vec2
    tangent_angle_deg: float
    normal_angle_deg: float
    long_side_cm: float = 4.0
    short_side_cm: float = 1.9


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    message: str
    related_circle_ids: list[int] = field(default_factory=list)
    related_connection_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class CourseSolution:
    tangents: list[TangentSegment | None]
    arcs: list[ArcSegment | None]
    issues: list[ValidationIssue]
    corner_markers: list[CornerMarker] = field(default_factory=list)
    start_goal_segment: StartGoalSegment | None = None
    start_goal_markers: list[StartGoalMarker] = field(default_factory=list)
