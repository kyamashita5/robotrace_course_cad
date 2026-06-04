from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from robotrace_course_cad.model.course_model import BoardGrid, CourseModel, HelperCircle, StartGoalHint, Turn


def load_course_model(path: str | Path) -> CourseModel:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    board = data.get("board", {})
    grid = data.get("grid", data.get("board_grid", {}))
    hint = data.get("start_goal_hint") or {}
    model = CourseModel(
        board_width_cm=float(board.get("width_cm", data.get("board_width_cm", 360.0))),
        board_height_cm=float(board.get("height_cm", data.get("board_height_cm", 180.0))),
        line_width_cm=float(data.get("line_width_cm", 1.9)),
        min_edge_margin_cm=float(data.get("min_edge_margin_cm", 20.0)),
        radius_presets_cm=[float(v) for v in data.get("radius_presets_cm", [10, 15, 20, 25, 30])],
        start_goal_hint=StartGoalHint(
            x=float(hint.get("x", 0.0)),
            y=float(hint.get("y", 0.0)),
            length=float(hint.get("length", 100.0)),
        ),
        board_grid=BoardGrid(
            origin_x=float(grid.get("origin_x_cm", grid.get("origin_x", 0.0))),
            origin_y=float(grid.get("origin_y_cm", grid.get("origin_y", 0.0))),
            cell_width=float(grid.get("cell_width_cm", grid.get("cell_width", 90.0))),
            cell_height=float(grid.get("cell_height_cm", grid.get("cell_height", 90.0))),
        ),
        circles=[
            HelperCircle(
                id=int(raw.get("id", index)),
                x=float(raw["x"]),
                y=float(raw["y"]),
                r=float(raw["r"]),
                turn=Turn.from_value(raw.get("turn", "ccw")),
                locked=bool(raw.get("locked", False)),
            )
            for index, raw in enumerate(data.get("circles", []))
        ],
    )
    model.renumber_circle_ids()
    return model


def save_course_model(model: CourseModel, path: str | Path) -> None:
    model.renumber_circle_ids()
    Path(path).write_text(json.dumps(course_model_to_dict(model), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def course_model_to_dict(model: CourseModel) -> dict[str, Any]:
    return {
        "board": {
            "width_cm": model.board_width_cm,
            "height_cm": model.board_height_cm,
        },
        "line_width_cm": model.line_width_cm,
        "min_edge_margin_cm": model.min_edge_margin_cm,
        "grid": {
            "origin_x_cm": model.board_grid.origin_x,
            "origin_y_cm": model.board_grid.origin_y,
            "cell_width_cm": model.board_grid.cell_width,
            "cell_height_cm": model.board_grid.cell_height,
        },
        "radius_presets_cm": model.radius_presets_cm,
        "start_goal_hint": {
            "x": model.start_goal_hint.x,
            "y": model.start_goal_hint.y,
            "length": model.start_goal_hint.length,
        },
        "circles": [
            {
                "id": circle.id,
                "x": circle.x,
                "y": circle.y,
                "r": circle.r,
                "turn": circle.turn.value,
                "locked": circle.locked,
            }
            for circle in model.circles
        ],
    }
