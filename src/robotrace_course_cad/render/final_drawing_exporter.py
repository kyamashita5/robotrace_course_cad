from __future__ import annotations

from pathlib import Path
import math

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QBrush, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QGraphicsScene

from robotrace_course_cad.model.course_model import BoardGrid, CourseModel, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution, TangentSegment
from robotrace_course_cad.render.qt_renderer import CM_TO_SCENE, _arc_path, _marker_polygon, to_scene

EXPORT_MARGIN_CM = 5.0
GRID_OUTLINE_WIDTH_CM = 0.2


def export_final_drawing(path: str | Path, model: CourseModel, solution: CourseSolution) -> None:
    export_path = Path(path)
    suffix = export_path.suffix.lower()
    scene = create_final_drawing_scene(model, solution)

    if suffix == ".svg":
        export_scene_to_svg(scene, export_path)
        return
    if suffix == ".pdf":
        export_scene_to_pdf(scene, export_path)
        return

    raise ValueError("Export path must end with .svg or .pdf")


def create_final_drawing_scene(model: CourseModel, solution: CourseSolution) -> QGraphicsScene:
    scene = QGraphicsScene()
    scene_rect = final_drawing_scene_rect(model, solution)
    scene.setSceneRect(scene_rect)

    _draw_occupied_grid_outlines(scene, model, solution)
    _draw_final_line(scene, model, solution)
    _draw_final_markers(scene, solution)
    return scene


def final_drawing_scene_rect(model: CourseModel, solution: CourseSolution) -> QRectF:
    min_x, max_x, min_y, max_y = final_drawing_bounds_cm(model, solution)
    return QRectF(
        min_x * CM_TO_SCENE,
        -max_y * CM_TO_SCENE,
        (max_x - min_x) * CM_TO_SCENE,
        (max_y - min_y) * CM_TO_SCENE,
    )


def final_drawing_bounds_cm(model: CourseModel, solution: CourseSolution) -> tuple[float, float, float, float]:
    line_half_width = model.line_width_cm / 2.0
    xs: list[float] = []
    ys: list[float] = []

    for tangent in solution.tangents:
        if tangent is None:
            continue
        xs.extend([tangent.p_from.x - line_half_width, tangent.p_from.x + line_half_width])
        xs.extend([tangent.p_to.x - line_half_width, tangent.p_to.x + line_half_width])
        ys.extend([tangent.p_from.y - line_half_width, tangent.p_from.y + line_half_width])
        ys.extend([tangent.p_to.y - line_half_width, tangent.p_to.y + line_half_width])

    for arc in solution.arcs:
        if arc is None:
            continue
        radius = arc.radius + line_half_width
        xs.extend([arc.center.x - radius, arc.center.x + radius])
        ys.extend([arc.center.y - radius, arc.center.y + radius])

    for marker in [*solution.corner_markers, *solution.start_goal_markers]:
        extent = max(marker.long_side_cm, marker.short_side_cm)
        xs.extend([marker.center.x - extent, marker.center.x + extent])
        ys.extend([marker.center.y - extent, marker.center.y + extent])

    for cell_x, cell_y in occupied_grid_cells(model, solution):
        min_cell_x, max_cell_x, min_cell_y, max_cell_y = cell_bounds_cm(model.board_grid, cell_x, cell_y)
        xs.extend([min_cell_x, max_cell_x])
        ys.extend([min_cell_y, max_cell_y])

    if not xs or not ys:
        return -10.0, 10.0, -10.0, 10.0

    min_x = math.floor((min(xs) - EXPORT_MARGIN_CM) * 10.0) / 10.0
    max_x = math.ceil((max(xs) + EXPORT_MARGIN_CM) * 10.0) / 10.0
    min_y = math.floor((min(ys) - EXPORT_MARGIN_CM) * 10.0) / 10.0
    max_y = math.ceil((max(ys) + EXPORT_MARGIN_CM) * 10.0) / 10.0
    return min_x, max_x, min_y, max_y


def export_scene_to_svg(scene: QGraphicsScene, path: Path) -> None:
    rect = scene.sceneRect()
    generator = QSvgGenerator()
    generator.setFileName(str(path))
    generator.setSize(QSize(math.ceil(rect.width()), math.ceil(rect.height())))
    generator.setViewBox(QRectF(0, 0, rect.width(), rect.height()))
    generator.setTitle("Robotrace Course Drawing")

    painter = QPainter(generator)
    try:
        scene.render(painter, QRectF(0, 0, rect.width(), rect.height()), rect)
    finally:
        painter.end()


def export_scene_to_pdf(scene: QGraphicsScene, path: Path) -> None:
    rect = scene.sceneRect()
    width_mm = rect.width() / CM_TO_SCENE * 10.0
    height_mm = rect.height() / CM_TO_SCENE * 10.0

    writer = QPdfWriter(str(path))
    writer.setResolution(300)
    writer.setPageSize(QPageSize(QSizeF(width_mm, height_mm), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)

    painter = QPainter(writer)
    try:
        scene.render(painter, QRectF(0, 0, writer.width(), writer.height()), rect)
    finally:
        painter.end()


def _draw_final_line(scene: QGraphicsScene, model: CourseModel, solution: CourseSolution) -> None:
    pen = QPen(QColor("#000000"), model.line_width_cm * CM_TO_SCENE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    for tangent in solution.tangents:
        if tangent is None:
            continue
        a = to_scene(tangent.p_from)
        b = to_scene(tangent.p_to)
        item = scene.addLine(a.x(), a.y(), b.x(), b.y(), pen)
        item.setZValue(10)

    for arc in solution.arcs:
        if arc is None:
            continue
        item = scene.addPath(_arc_path(arc), pen)
        item.setZValue(10)


def _draw_occupied_grid_outlines(scene: QGraphicsScene, model: CourseModel, solution: CourseSolution) -> None:
    cells = occupied_grid_cells(model, solution)
    if not cells:
        return

    pen = QPen(QColor("#000000"), GRID_OUTLINE_WIDTH_CM * CM_TO_SCENE)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)

    for cell_x, cell_y in sorted(cells):
        min_x, max_x, min_y, max_y = cell_bounds_cm(model.board_grid, cell_x, cell_y)
        rect = QRectF(
            min_x * CM_TO_SCENE,
            -max_y * CM_TO_SCENE,
            (max_x - min_x) * CM_TO_SCENE,
            (max_y - min_y) * CM_TO_SCENE,
        )
        item = scene.addRect(rect, pen)
        item.setZValue(5)


def _draw_final_markers(scene: QGraphicsScene, solution: CourseSolution) -> None:
    pen = QPen(QColor("#000000"), 0)
    brush = QBrush(QColor("#000000"))

    for marker in solution.corner_markers:
        item = scene.addPolygon(_marker_polygon(marker), pen, brush)
        item.setZValue(20)

    for marker in solution.start_goal_markers:
        item = scene.addPolygon(_marker_polygon(marker), pen, brush)
        item.setZValue(20)


def occupied_grid_cells(model: CourseModel, solution: CourseSolution) -> set[tuple[int, int]]:
    grid = model.board_grid
    if not grid.enabled:
        return set()

    cells: set[tuple[int, int]] = set()
    sample_step = max(1.0, min(5.0, min(grid.cell_width, grid.cell_height) / 5.0))
    line_half_width = model.line_width_cm / 2.0

    for tangent in solution.tangents:
        if tangent is not None:
            for point in sample_tangent(tangent, sample_step):
                mark_cells_near_point(cells, grid, point, line_half_width)

    for arc in solution.arcs:
        if arc is not None:
            for point in sample_arc(arc, sample_step):
                mark_cells_near_point(cells, grid, point, line_half_width)

    return cells


def sample_tangent(tangent: TangentSegment, step_cm: float) -> list:
    length = tangent.length
    if length <= 1e-9:
        return [tangent.p_from]
    count = max(1, math.ceil(length / step_cm))
    return [tangent.p_from + (tangent.p_to - tangent.p_from) * (i / count) for i in range(count + 1)]


def sample_arc(arc: ArcSegment, step_cm: float) -> list:
    count = max(1, math.ceil(arc.length / step_cm))
    start_angle = math.atan2(arc.p_start.y - arc.center.y, arc.p_start.x - arc.center.x)
    direction = 1.0 if arc.turn == Turn.CCW else -1.0
    points = []
    for i in range(count + 1):
        angle = start_angle + direction * arc.angle_rad * (i / count)
        points.append(
            type(arc.center)(
                arc.center.x + arc.radius * math.cos(angle),
                arc.center.y + arc.radius * math.sin(angle),
            )
        )
    return points


def mark_cells_near_point(cells: set[tuple[int, int]], grid: BoardGrid, point, radius_cm: float) -> None:
    base_x, base_y = point_cell_index(grid, point.x, point.y)
    neighbor_radius = max(1, math.ceil(radius_cm / min(grid.cell_width, grid.cell_height)) + 1)

    for ix in range(base_x - neighbor_radius, base_x + neighbor_radius + 1):
        for iy in range(base_y - neighbor_radius, base_y + neighbor_radius + 1):
            min_x, max_x, min_y, max_y = cell_bounds_cm(grid, ix, iy)
            if point_to_rect_distance(point.x, point.y, min_x, max_x, min_y, max_y) <= radius_cm + 1e-6:
                cells.add((ix, iy))


def point_cell_index(grid: BoardGrid, x: float, y: float) -> tuple[int, int]:
    return (
        math.floor((x - grid.origin_x) / grid.cell_width),
        math.floor((y - grid.origin_y) / grid.cell_height),
    )


def cell_bounds_cm(grid: BoardGrid, cell_x: int, cell_y: int) -> tuple[float, float, float, float]:
    min_x = grid.origin_x + cell_x * grid.cell_width
    max_x = min_x + grid.cell_width
    min_y = grid.origin_y + cell_y * grid.cell_height
    max_y = min_y + grid.cell_height
    return min_x, max_x, min_y, max_y


def point_to_rect_distance(x: float, y: float, min_x: float, max_x: float, min_y: float, max_y: float) -> float:
    dx = max(min_x - x, 0.0, x - max_x)
    dy = max(min_y - y, 0.0, y - max_y)
    return math.hypot(dx, dy)
