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

    def renumber_circle_ids(self) -> None:
        for index, circle in enumerate(self.circles):
            circle.id = index

    def next_circle_id(self) -> int:
        return len(self.circles)


def default_course_model() -> CourseModel:
    return CourseModel(
        board_width_cm=360.0,
        board_height_cm=180.0,
        line_width_cm=1.9,
        min_edge_margin_cm=20.0,
        radius_presets_cm=[10, 15, 20, 25, 30, 40, 50],
        circles=[
            HelperCircle(0, 65.0, 225.0, 25.0, Turn.CW),
            HelperCircle(1, 320.0, 230.0, 20.0, Turn.CW),
            HelperCircle(2, 210.0, 50.0, 30.0, Turn.CW),
            HelperCircle(3, 60.0, 40.0, 20.0, Turn.CW),
        ],
        start_goal_hint=StartGoalHint(40.0, 135.0, 100.0),
        board_grid=BoardGrid(0.0, 0.0, 90.0, 135.0),
    )
