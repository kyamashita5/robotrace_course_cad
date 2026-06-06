from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import math

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QBrush,
    QFont,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPdfWriter,
    QPen,
    QPolygonF,
    QTextOption,
)
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QGraphicsScene, QGraphicsTextItem

from robotrace_course_cad.model.course_model import BoardGrid, CourseModel, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution, TangentSegment
from robotrace_course_cad.render.qt_renderer import CM_TO_SCENE, _arc_path, _marker_polygon, start_goal_area_points, to_scene

EXPORT_MARGIN_CM = 5.0
BOARD_LINE_PROXIMITY_CM = 19.0
FINAL_START_GOAL_AREA_EXTENSION_CM = 10.0
FINAL_START_GOAL_AREA_WIDTH_CM = 1.0
FINAL_START_GOAL_OUTER_AREA_HALF_WIDTH_CM = 40.0
START_GOAL_GATE_WIDTH_CM = 40.0
START_GOAL_GATE_LENGTH_CM = 10.0
HELPER_CIRCLE_WIDTH_CM = 0.48
HELPER_LABEL_PIXEL_SIZE = 39
LABEL_LINE_PROTECTION_PADDING_SCENE = 2.0
START_GOAL_GATE_LABEL_PIXEL_SIZE = HELPER_LABEL_PIXEL_SIZE
START_GOAL_GATE_COORD_PIXEL_SIZE = HELPER_LABEL_PIXEL_SIZE
A4_WIDTH_MM = 297.0
A4_HEIGHT_MM = 210.0
A4_MARGIN_MM = 8.0
SVG_DPI = 72.0
FINAL_BLACK = QColor("#000000")
BOARD_CYAN = QColor("#00a9dc")
HELPER_MAGENTA = QColor("#ff2a5a")
START_GOAL_AREA_YELLOW = QColor("#f2c400")
START_GOAL_OUTER_AREA_GRAY = QColor("#8d8d8d")


@dataclass(frozen=True)
class FinalDrawingOptions:
    print_helper_circles: bool = False
    print_corner_markers: bool = True
    print_start_goal_markers: bool = True
    print_start_goal_area: bool = True
    print_start_goal_outer_area: bool = False


def export_final_drawing(
    path: str | Path,
    model: CourseModel,
    solution: CourseSolution,
    options: FinalDrawingOptions | None = None,
) -> None:
    export_path = Path(path)
    suffix = export_path.suffix.lower()
    scene = create_final_drawing_scene(model, solution, options or FinalDrawingOptions())

    if suffix == ".svg":
        export_scene_to_svg(scene, export_path)
        return
    if suffix == ".pdf":
        export_scene_to_pdf(scene, export_path)
        return

    raise ValueError("Export path must end with .svg or .pdf")


def create_final_drawing_scene(
    model: CourseModel,
    solution: CourseSolution,
    options: FinalDrawingOptions | None = None,
) -> QGraphicsScene:
    options = options or FinalDrawingOptions()
    scene = QGraphicsScene()
    scene_rect = final_drawing_scene_rect(model, solution, options)
    scene.setSceneRect(scene_rect)

    _draw_occupied_grid_outlines(scene, model, solution)
    protected_text_rects: list[QRectF] = []
    if options.print_start_goal_area:
        _draw_final_start_goal_area(scene, solution, protected_text_rects, options)
    _draw_final_line(scene, model, solution)
    _draw_final_markers(scene, solution, options)
    if options.print_helper_circles:
        _draw_helper_circles(scene, model, protected_text_rects, line_label_protection_paths(model, solution))
    return scene


def final_drawing_scene_rect(
    model: CourseModel,
    solution: CourseSolution,
    options: FinalDrawingOptions | None = None,
) -> QRectF:
    min_x, max_x, min_y, max_y = final_drawing_bounds_cm(model, solution, options or FinalDrawingOptions())
    return QRectF(
        min_x * CM_TO_SCENE,
        -max_y * CM_TO_SCENE,
        (max_x - min_x) * CM_TO_SCENE,
        (max_y - min_y) * CM_TO_SCENE,
    )


def final_drawing_bounds_cm(
    model: CourseModel,
    solution: CourseSolution,
    options: FinalDrawingOptions | None = None,
) -> tuple[float, float, float, float]:
    options = options or FinalDrawingOptions()
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

    markers = []
    if options.print_corner_markers:
        markers.extend(solution.corner_markers)
    if options.print_start_goal_markers:
        markers.extend(solution.start_goal_markers)
    for marker in markers:
        extent = max(marker.long_side_cm, marker.short_side_cm)
        xs.extend([marker.center.x - extent, marker.center.x + extent])
        ys.extend([marker.center.y - extent, marker.center.y + extent])

    for cell_x, cell_y in occupied_grid_cells(model, solution):
        min_cell_x, max_cell_x, min_cell_y, max_cell_y = cell_bounds_cm(model.board_grid, cell_x, cell_y)
        xs.extend([min_cell_x, max_cell_x])
        ys.extend([min_cell_y, max_cell_y])

    if options.print_helper_circles:
        for circle in model.circles:
            xs.extend([circle.x - circle.r, circle.x + circle.r])
            ys.extend([circle.y - circle.r, circle.y + circle.r])

    if options.print_start_goal_area and solution.start_goal_segment is not None:
        for point in start_goal_area_points(solution.start_goal_segment, FINAL_START_GOAL_AREA_EXTENSION_CM):
            xs.append(point.x)
            ys.append(point.y)
        if options.print_start_goal_outer_area:
            for point in final_start_goal_outer_area_points(solution.start_goal_segment):
                xs.append(point.x)
                ys.append(point.y)
        for point in start_goal_gate_points(solution.start_goal_segment.p_start, solution.start_goal_segment):
            xs.append(point.x)
            ys.append(point.y)
        for point in start_goal_gate_points(solution.start_goal_segment.p_end, solution.start_goal_segment):
            xs.append(point.x)
            ys.append(point.y)

    if not xs or not ys:
        return -10.0, 10.0, -10.0, 10.0

    min_x = math.floor((min(xs) - EXPORT_MARGIN_CM) * 10.0) / 10.0
    max_x = math.ceil((max(xs) + EXPORT_MARGIN_CM) * 10.0) / 10.0
    min_y = math.floor((min(ys) - EXPORT_MARGIN_CM) * 10.0) / 10.0
    max_y = math.ceil((max(ys) + EXPORT_MARGIN_CM) * 10.0) / 10.0
    return min_x, max_x, min_y, max_y


def export_scene_to_svg(scene: QGraphicsScene, path: Path) -> None:
    rect = scene.sceneRect()
    page_width = A4_WIDTH_MM
    page_height = A4_HEIGHT_MM
    if rect.height() > rect.width():
        page_width, page_height = A4_HEIGHT_MM, A4_WIDTH_MM

    generator = QSvgGenerator()
    generator.setFileName(str(path))
    generator.setSize(svg_pixel_size_for_mm(page_width, page_height))
    generator.setViewBox(QRectF(0, 0, page_width, page_height))
    generator.setTitle("Robotrace Course Drawing")

    painter = QPainter(generator)
    try:
        target = fitted_target_rect(rect, page_width, page_height, A4_MARGIN_MM)
        scene.render(painter, target, rect)
    finally:
        painter.end()


def export_scene_to_pdf(scene: QGraphicsScene, path: Path) -> None:
    rect = scene.sceneRect()
    page_width = A4_WIDTH_MM
    page_height = A4_HEIGHT_MM
    if rect.height() > rect.width():
        page_width, page_height = A4_HEIGHT_MM, A4_WIDTH_MM

    writer = QPdfWriter(str(path))
    writer.setResolution(300)
    writer.setPageSize(QPageSize(QSizeF(page_width, page_height), QPageSize.Unit.Millimeter))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)

    painter = QPainter(writer)
    try:
        scale_x = writer.width() / page_width
        scale_y = writer.height() / page_height
        target_mm = fitted_target_rect(rect, page_width, page_height, A4_MARGIN_MM)
        target_device = QRectF(
            target_mm.x() * scale_x,
            target_mm.y() * scale_y,
            target_mm.width() * scale_x,
            target_mm.height() * scale_y,
        )
        scene.render(painter, target_device, rect)
    finally:
        painter.end()


def fitted_target_rect(source: QRectF, page_width: float, page_height: float, margin: float) -> QRectF:
    available_width = max(1.0, page_width - margin * 2.0)
    available_height = max(1.0, page_height - margin * 2.0)
    scale = min(available_width / source.width(), available_height / source.height())
    width = source.width() * scale
    height = source.height() * scale
    return QRectF((page_width - width) / 2.0, (page_height - height) / 2.0, width, height)


def svg_pixel_size_for_mm(width_mm: float, height_mm: float) -> QSize:
    return QSize(
        max(1, round(width_mm / 25.4 * SVG_DPI)),
        max(1, round(height_mm / 25.4 * SVG_DPI)),
    )


def _draw_final_line(scene: QGraphicsScene, model: CourseModel, solution: CourseSolution) -> None:
    pen = QPen(FINAL_BLACK, model.line_width_cm * CM_TO_SCENE)
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


def line_label_protection_paths(model: CourseModel, solution: CourseSolution) -> list[QPainterPath]:
    stroker = QPainterPathStroker()
    stroker.setWidth(model.line_width_cm * CM_TO_SCENE + 2.0 * LABEL_LINE_PROTECTION_PADDING_SCENE)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    paths: list[QPainterPath] = []
    for tangent in solution.tangents:
        if tangent is None:
            continue
        path = QPainterPath(to_scene(tangent.p_from))
        path.lineTo(to_scene(tangent.p_to))
        paths.append(stroker.createStroke(path))

    for arc in solution.arcs:
        if arc is None:
            continue
        paths.append(stroker.createStroke(_arc_path(arc)))

    return paths


def _draw_occupied_grid_outlines(scene: QGraphicsScene, model: CourseModel, solution: CourseSolution) -> None:
    cells = occupied_grid_cells(model, solution)
    if not cells:
        return

    pen = QPen(BOARD_CYAN, model.line_width_cm * CM_TO_SCENE)
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


def _draw_final_start_goal_area(
    scene: QGraphicsScene,
    solution: CourseSolution,
    protected_text_rects: list[QRectF],
    options: FinalDrawingOptions,
) -> None:
    if solution.start_goal_segment is None:
        return

    pen = QPen(START_GOAL_AREA_YELLOW, FINAL_START_GOAL_AREA_WIDTH_CM * CM_TO_SCENE)
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    if options.print_start_goal_outer_area:
        outer_pen = QPen(START_GOAL_OUTER_AREA_GRAY, FINAL_START_GOAL_AREA_WIDTH_CM * CM_TO_SCENE)
        outer_pen.setStyle(Qt.PenStyle.DashLine)
        outer_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        outer_polygon = QPolygonF(
            [to_scene(point) for point in final_start_goal_outer_area_points(solution.start_goal_segment)]
        )
        outer_item = scene.addPolygon(outer_polygon, outer_pen)
        outer_item.setZValue(7)

    polygon = QPolygonF(
        [to_scene(point) for point in start_goal_area_points(solution.start_goal_segment, FINAL_START_GOAL_AREA_EXTENSION_CM)]
    )
    item = scene.addPolygon(polygon, pen)
    item.setZValue(8)

    _draw_start_goal_gate(scene, "GOAL", solution.start_goal_segment.p_start, solution.start_goal_segment, protected_text_rects)
    _draw_start_goal_gate(scene, "START", solution.start_goal_segment.p_end, solution.start_goal_segment, protected_text_rects)


def _draw_start_goal_gate(
    scene: QGraphicsScene,
    label: str,
    point,
    segment,
    protected_text_rects: list[QRectF],
) -> None:
    gate_pen = QPen(FINAL_BLACK, 1.0 * CM_TO_SCENE)
    gate_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    polygon = QPolygonF([to_scene(corner) for corner in start_goal_gate_points(point, segment)])
    item = scene.addPolygon(polygon, gate_pen)
    item.setZValue(12)

    direction = (segment.p_end - segment.p_start).normalized()
    left = direction.left_normal().normalized()
    text_rotation_deg = start_goal_text_rotation_angle(segment)
    coordinate_anchor_edge = start_goal_coordinate_anchor_edge(segment, text_rotation_deg)
    label_center = point + left * (START_GOAL_GATE_WIDTH_CM * 0.25)
    protected_text_rects.append(
        add_centered_text(
            scene,
            label,
            label_center,
            FINAL_BLACK,
            START_GOAL_GATE_LABEL_PIXEL_SIZE,
            z=32,
            rotation_deg=text_rotation_deg,
        )
    )
    protected_text_rects.append(
        add_right_aligned_text(
            scene,
            start_goal_coordinate_text(point),
            start_goal_coordinate_anchor(point, segment),
            HELPER_MAGENTA,
            START_GOAL_GATE_COORD_PIXEL_SIZE,
            z=32,
            rotation_deg=text_rotation_deg,
            anchor_edge=coordinate_anchor_edge,
        )
    )


def start_goal_gate_points(point, segment) -> list:
    direction = (segment.p_end - segment.p_start).normalized()
    left = direction.left_normal().normalized()
    half_length = START_GOAL_GATE_LENGTH_CM / 2.0
    half_width = START_GOAL_GATE_WIDTH_CM / 2.0
    return [
        point - direction * half_length + left * half_width,
        point + direction * half_length + left * half_width,
        point + direction * half_length - left * half_width,
        point - direction * half_length - left * half_width,
    ]


def final_start_goal_outer_area_points(segment) -> list:
    return start_goal_area_points(
        segment,
        extension_cm=FINAL_START_GOAL_AREA_EXTENSION_CM,
        half_width_cm=FINAL_START_GOAL_OUTER_AREA_HALF_WIDTH_CM,
    )


def start_goal_coordinate_text(point) -> str:
    return f"{format_coordinate(point.x)},{format_coordinate(point.y)}"


def start_goal_coordinate_anchor(point, segment):
    direction = (segment.p_end - segment.p_start).normalized()
    left = direction.left_normal().normalized()
    return point - left * (START_GOAL_GATE_WIDTH_CM / 2.0)


def start_goal_text_rotation_angle(segment) -> float:
    direction = (segment.p_end - segment.p_start).normalized()
    left = direction.left_normal().normalized()
    scene_angle = math.degrees(math.atan2(-left.y, left.x))
    return readable_text_angle(scene_angle)


def start_goal_coordinate_anchor_edge(segment, rotation_deg: float) -> str:
    if not math.isclose(abs(rotation_deg), 90.0, abs_tol=1e-6):
        return "right"

    direction = (segment.p_end - segment.p_start).normalized()
    inward = direction.left_normal().normalized()
    inward_scene_y = -inward.y
    if rotation_deg < 0.0:
        return "left" if inward_scene_y < 0.0 else "right"
    return "right" if inward_scene_y < 0.0 else "left"


def readable_text_angle(angle_deg: float) -> float:
    angle = angle_deg
    while angle <= -180.0:
        angle += 360.0
    while angle > 180.0:
        angle -= 360.0
    if angle > 90.0:
        angle -= 180.0
    elif angle < -90.0:
        angle += 180.0
    if math.isclose(angle, 90.0, abs_tol=1e-6):
        return -90.0
    return angle


def rotated_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def position_text_item_by_local_anchor(
    item: QGraphicsTextItem,
    scene_anchor,
    local_anchor_x: float,
    local_anchor_y: float,
    rotation_deg: float,
) -> None:
    rotated_x, rotated_y = rotated_point(local_anchor_x, local_anchor_y, rotation_deg)
    item.setRotation(rotation_deg)
    item.setPos(scene_anchor.x() - rotated_x, scene_anchor.y() - rotated_y)


def add_centered_text(
    scene: QGraphicsScene,
    text: str,
    center,
    color: QColor,
    pixel_size: int,
    z: float,
    rotation_deg: float = 0.0,
) -> QRectF:
    item = QGraphicsTextItem()
    font = QFont("Arial")
    font.setPixelSize(pixel_size)
    font.setBold(True)
    item.setFont(font)
    item.setDefaultTextColor(color)
    item.setPlainText(text)
    item.document().setDocumentMargin(0.0)
    item.setTextWidth(item.document().idealWidth())
    rect = item.boundingRect()
    scene_center = to_scene(center)
    position_text_item_by_local_anchor(item, scene_center, rect.width() / 2.0, rect.height() / 2.0, rotation_deg)
    item.setZValue(z)
    scene.addItem(item)
    return item.sceneBoundingRect()


def add_right_aligned_text(
    scene: QGraphicsScene,
    text: str,
    anchor,
    color: QColor,
    pixel_size: int,
    z: float,
    rotation_deg: float = 0.0,
    anchor_edge: str = "right",
) -> QRectF:
    item = QGraphicsTextItem()
    font = QFont("Arial")
    font.setPixelSize(pixel_size)
    font.setBold(True)
    item.setFont(font)
    item.setDefaultTextColor(color)
    item.setPlainText(text)
    item.document().setDocumentMargin(0.0)
    text_option = QTextOption()
    if anchor_edge == "left":
        text_option.setAlignment(Qt.AlignmentFlag.AlignLeft)
    else:
        text_option.setAlignment(Qt.AlignmentFlag.AlignRight)
    item.document().setDefaultTextOption(text_option)
    item.setTextWidth(item.document().idealWidth())
    rect = item.boundingRect()
    scene_anchor = to_scene(anchor)
    local_anchor_x = rect.left() if anchor_edge == "left" else rect.right()
    position_text_item_by_local_anchor(item, scene_anchor, local_anchor_x, rect.center().y(), rotation_deg)
    item.setZValue(z)
    scene.addItem(item)
    return item.sceneBoundingRect()


def _draw_final_markers(scene: QGraphicsScene, solution: CourseSolution, options: FinalDrawingOptions) -> None:
    pen = QPen(FINAL_BLACK, 0)
    brush = QBrush(FINAL_BLACK)

    if options.print_corner_markers:
        for marker in solution.corner_markers:
            item = scene.addPolygon(_marker_polygon(marker), pen, brush)
            item.setZValue(20)

    if options.print_start_goal_markers:
        for marker in solution.start_goal_markers:
            item = scene.addPolygon(_marker_polygon(marker), pen, brush)
            item.setZValue(20)


def _draw_helper_circles(
    scene: QGraphicsScene,
    model: CourseModel,
    protected_text_rects: list[QRectF] | None = None,
    protected_paths: list[QPainterPath] | None = None,
) -> None:
    pen = QPen(HELPER_MAGENTA, HELPER_CIRCLE_WIDTH_CM * CM_TO_SCENE)
    text_rects: list[QRectF] = list(protected_text_rects or [])
    paths = protected_paths or []

    for circle in sorted(model.circles, key=lambda c: (c.r, c.id)):
        r_scene = circle.r * CM_TO_SCENE
        center = to_scene(circle.center)
        item = scene.addEllipse(
            center.x() - r_scene,
            center.y() - r_scene,
            2.0 * r_scene,
            2.0 * r_scene,
            pen,
        )
        item.setZValue(30)
        text_item = _helper_circle_text_item(circle)
        _place_helper_circle_text(text_item, center, r_scene, text_rects, paths)
        scene.addItem(text_item)


def _helper_circle_text_item(circle) -> QGraphicsTextItem:
    item = QGraphicsTextItem()
    font = QFont("Arial")
    font.setPixelSize(HELPER_LABEL_PIXEL_SIZE)
    font.setBold(True)
    item.setFont(font)
    item.setDefaultTextColor(HELPER_MAGENTA)
    item.setPlainText(helper_circle_label_text(circle))
    item.document().setDocumentMargin(0.0)
    text_option = QTextOption()
    text_option.setAlignment(Qt.AlignmentFlag.AlignCenter)
    item.document().setDefaultTextOption(text_option)
    item.setTextWidth(item.document().idealWidth())
    item.setZValue(31)
    return item


def helper_circle_label_text(circle) -> str:
    center_x = format_coordinate(circle.x)
    center_y = format_coordinate(circle.y)
    radius_text = f"R{format_radius(circle.r)}"
    if circle.r >= 20.0:
        return f"{radius_text}\n{center_x}, {center_y}"
    return f"{radius_text}\n{center_x},\n{center_y}"


def _place_helper_circle_text(
    item: QGraphicsTextItem,
    center,
    radius_scene: float,
    placed_rects: list[QRectF],
    protected_paths: list[QPainterPath] | None = None,
) -> None:
    local_rect = item.boundingRect()
    offsets = helper_label_offsets(radius_scene)
    paths = protected_paths or []
    for dx, dy in offsets:
        pos_x = center.x() + dx - local_rect.width() / 2.0
        pos_y = center.y() + dy - local_rect.height() / 2.0
        candidate = QRectF(pos_x, pos_y, local_rect.width(), local_rect.height())
        if not any(candidate.intersects(rect.adjusted(-2, -2, 2, 2)) for rect in placed_rects) and not label_rect_intersects_paths(
            candidate, paths
        ):
            item.setPos(pos_x, pos_y)
            placed_rects.append(candidate)
            return

    pos_x = center.x() - local_rect.width() / 2.0
    pos_y = center.y() - local_rect.height() / 2.0
    fallback = QRectF(pos_x, pos_y, local_rect.width(), local_rect.height())
    item.setPos(pos_x, pos_y)
    placed_rects.append(fallback)


def label_rect_intersects_paths(rect: QRectF, paths: list[QPainterPath]) -> bool:
    if not paths:
        return False
    rect_path = QPainterPath()
    rect_path.addRect(rect)
    center = rect.center()
    return any(path.intersects(rect_path) or path.contains(center) for path in paths)


def helper_label_offsets(radius_scene: float) -> list[tuple[float, float]]:
    offsets = [(0.0, 0.0)]
    step = max(radius_scene * 0.35, 18.0)
    for ring in range(1, 12):
        distance = step * ring
        for angle_deg in range(0, 360, 45):
            angle = math.radians(angle_deg)
            offsets.append((math.cos(angle) * distance, math.sin(angle) * distance))
    return offsets


def format_radius(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def format_coordinate(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.1f}"


def occupied_grid_cells(model: CourseModel, solution: CourseSolution) -> set[tuple[int, int]]:
    grid = model.board_grid
    if not grid.enabled:
        return set()

    cells: set[tuple[int, int]] = set()
    sample_step = max(1.0, min(5.0, min(grid.cell_width, grid.cell_height) / 5.0))
    line_half_width = model.line_width_cm / 2.0
    board_detection_distance = line_half_width + BOARD_LINE_PROXIMITY_CM

    for tangent in solution.tangents:
        if tangent is not None:
            for point in sample_tangent(tangent, sample_step):
                mark_cells_near_point(cells, grid, point, board_detection_distance)

    for arc in solution.arcs:
        if arc is not None:
            for point in sample_arc(arc, sample_step):
                mark_cells_near_point(cells, grid, point, board_detection_distance)

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
