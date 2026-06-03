from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .geometry import Vec2


class Turn(Enum):
    CW = "cw"
    CCW = "ccw"

    @classmethod
    def from_value(cls, value: str | Turn) -> Turn:
        if isinstance(value, Turn):
            return value
        normalized = str(value).lower()
        if normalized in {"cw", "clockwise"}:
            return cls.CW
        if normalized in {"ccw", "counterclockwise", "counter-clockwise"}:
            return cls.CCW
        raise ValueError(f"Unknown turn direction: {value!r}")


@dataclass
class HelperCircle:
    id: int
    x: float
    y: float
    r: float
    turn: Turn
    locked: bool = False

    @property
    def center(self) -> Vec2:
        return Vec2(self.x, self.y)


@dataclass
class StartGoalHint:
    x: float
    y: float
    length: float = 100.0

    @property
    def center(self) -> Vec2:
        return Vec2(self.x, self.y)


@dataclass
class BoardGrid:
    origin_x: float = 0.0
    origin_y: float = 0.0
    cell_width: float = 90.0
    cell_height: float = 90.0

    @property
    def enabled(self) -> bool:
        return self.cell_width > 0.0 and self.cell_height > 0.0


@dataclass
class CourseModel:
    board_width_cm: float = 360.0
    board_height_cm: float = 180.0
    line_width_cm: float = 1.9
    min_edge_margin_cm: float = 20.0
    radius_presets_cm: list[float] = field(default_factory=lambda: [10, 15, 20, 25, 30, 40, 50])
    circles: list[HelperCircle] = field(default_factory=list)
    start_goal_hint: StartGoalHint = field(default_factory=lambda: StartGoalHint(30.0, -45.0))
    board_grid: BoardGrid = field(default_factory=BoardGrid)

    def next_circle_id(self) -> int:
        used_ids = {circle.id for circle in self.circles}
        next_id = 0
        while next_id in used_ids:
            next_id += 1
        return next_id


def default_course_model() -> CourseModel:
    return CourseModel(
        circles=[
            HelperCircle(0, -60.0, 0.0, 25.0, Turn.CCW),
            HelperCircle(1, 20.0, 45.0, 20.0, Turn.CW),
            HelperCircle(2, 85.0, -10.0, 30.0, Turn.CCW),
            HelperCircle(3, 10.0, -55.0, 20.0, Turn.CW),
        ],
        start_goal_hint=StartGoalHint(-25.0, -55.0, 100.0),
    )
