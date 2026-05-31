from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem

from robotrace_course_cad.model.course_model import CourseModel, HelperCircle, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CornerMarker, CourseSolution, StartGoalMarker
from robotrace_course_cad.model.geometry import Vec2

CM_TO_SCENE = 10.0


def to_scene(point: Vec2) -> QPointF:
    return QPointF(point.x * CM_TO_SCENE, -point.y * CM_TO_SCENE)


def from_scene(point: QPointF) -> Vec2:
    return Vec2(point.x() / CM_TO_SCENE, -point.y() / CM_TO_SCENE)


class HelperCircleItem(QGraphicsEllipseItem):
    def __init__(self, circle: HelperCircle, on_changed):
        r = circle.r * CM_TO_SCENE
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.circle = circle
        self.on_changed = on_changed
        self.setPos(to_scene(circle.center))
        self.setPen(QPen(QColor("#4d83d8"), 1.4))
        self.setBrush(QBrush(QColor(80, 130, 216, 26)))
        self.setFlag(QGraphicsItem.ItemIsMovable, not circle.locked)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setZValue(10)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            pos = self.pos()
            self.circle.x = pos.x() / CM_TO_SCENE
            self.circle.y = -pos.y() / CM_TO_SCENE
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.on_changed(self.circle)


def render_course(scene: QGraphicsScene, model: CourseModel, solution: CourseSolution, on_circle_changed) -> None:
    scene.clear()
    scene_rect = _course_scene_rect(model, solution)
    scene.setSceneRect(scene_rect)
    _draw_grid(scene, scene_rect)
    _draw_generated_line(scene, model, solution)
    _draw_corner_markers(scene, solution)
    _draw_start_goal_markers(scene, solution)
    _draw_helper_connections(scene, model)
    _draw_helper_circles(scene, model, on_circle_changed)
    _draw_start_goal_hint(scene, model)


def _course_scene_rect(model: CourseModel, solution: CourseSolution, margin_cm: float = 80.0) -> QRectF:
    min_x, max_x, min_y, max_y = _course_bounds_cm(model, solution, margin_cm)
    return QRectF(
        min_x * CM_TO_SCENE,
        -max_y * CM_TO_SCENE,
        (max_x - min_x) * CM_TO_SCENE,
        (max_y - min_y) * CM_TO_SCENE,
    )


def _course_bounds_cm(model: CourseModel, solution: CourseSolution, margin_cm: float = 80.0) -> tuple[float, float, float, float]:
    xs: list[float] = [model.start_goal_hint.x]
    ys: list[float] = [model.start_goal_hint.y]

    for circle in model.circles:
        xs.extend([circle.x - circle.r, circle.x + circle.r])
        ys.extend([circle.y - circle.r, circle.y + circle.r])

    for tangent in solution.tangents:
        if tangent is None:
            continue
        xs.extend([tangent.p_from.x, tangent.p_to.x])
        ys.extend([tangent.p_from.y, tangent.p_to.y])

    for arc in solution.arcs:
        if arc is None:
            continue
        xs.extend([arc.center.x - arc.radius, arc.center.x + arc.radius, arc.p_start.x, arc.p_end.x])
        ys.extend([arc.center.y - arc.radius, arc.center.y + arc.radius, arc.p_start.y, arc.p_end.y])

    for marker in solution.corner_markers:
        xs.extend([marker.center.x - marker.long_side_cm, marker.center.x + marker.long_side_cm])
        ys.extend([marker.center.y - marker.long_side_cm, marker.center.y + marker.long_side_cm])

    if solution.start_goal_segment is not None:
        segment = solution.start_goal_segment
        xs.extend([segment.p_start.x, segment.p_end.x, segment.center.x])
        ys.extend([segment.p_start.y, segment.p_end.y, segment.center.y])

    for marker in solution.start_goal_markers:
        xs.extend([marker.center.x - marker.long_side_cm, marker.center.x + marker.long_side_cm])
        ys.extend([marker.center.y - marker.long_side_cm, marker.center.y + marker.long_side_cm])

    if not xs or not ys:
        return -200.0, 200.0, -140.0, 140.0

    min_x = min(xs) - margin_cm
    max_x = max(xs) + margin_cm
    min_y = min(ys) - margin_cm
    max_y = max(ys) + margin_cm

    min_x = math.floor(min_x / 10.0) * 10.0
    max_x = math.ceil(max_x / 10.0) * 10.0
    min_y = math.floor(min_y / 10.0) * 10.0
    max_y = math.ceil(max_y / 10.0) * 10.0

    if max_x - min_x < 200.0:
        center_x = (min_x + max_x) / 2.0
        min_x = center_x - 100.0
        max_x = center_x + 100.0
    if max_y - min_y < 160.0:
        center_y = (min_y + max_y) / 2.0
        min_y = center_y - 80.0
        max_y = center_y + 80.0

    return min_x, max_x, min_y, max_y


def _draw_grid(scene: QGraphicsScene, scene_rect: QRectF) -> None:
    light = QPen(QColor("#eceff3"), 0)
    axis = QPen(QColor("#c8ced8"), 0)
    min_x_cm = math.floor(scene_rect.left() / CM_TO_SCENE / 10.0) * 10
    max_x_cm = math.ceil(scene_rect.right() / CM_TO_SCENE / 10.0) * 10
    min_y_cm = math.floor((-scene_rect.bottom()) / CM_TO_SCENE / 10.0) * 10
    max_y_cm = math.ceil((-scene_rect.top()) / CM_TO_SCENE / 10.0) * 10

    for x_cm in range(int(min_x_cm), int(max_x_cm) + 1, 10):
        pen = axis if x_cm == 0 else light
        x = x_cm * CM_TO_SCENE
        scene.addLine(x, scene_rect.top(), x, scene_rect.bottom(), pen)

    for y_cm in range(int(min_y_cm), int(max_y_cm) + 1, 10):
        pen = axis if y_cm == 0 else light
        y = -y_cm * CM_TO_SCENE
        scene.addLine(scene_rect.left(), y, scene_rect.right(), y, pen)


def _draw_generated_line(scene: QGraphicsScene, model: CourseModel, solution: CourseSolution) -> None:
    width_pen = QPen(QColor(35, 35, 35, 55), model.line_width_cm * CM_TO_SCENE)
    width_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    width_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    center_pen = QPen(QColor("#202020"), 2.0)
    center_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    center_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    for pen, z in ((width_pen, 20), (center_pen, 21)):
        for tangent in solution.tangents:
            if tangent is None:
                continue
            item = scene.addLine(
                to_scene(tangent.p_from).x(),
                to_scene(tangent.p_from).y(),
                to_scene(tangent.p_to).x(),
                to_scene(tangent.p_to).y(),
                pen,
            )
            item.setZValue(z)

        for arc in solution.arcs:
            if arc is None:
                continue
            item = QGraphicsPathItem(_arc_path(arc))
            item.setPen(pen)
            item.setZValue(z)
            scene.addItem(item)


def _arc_path(arc: ArcSegment) -> QPainterPath:
    start = to_scene(arc.p_start)
    path = QPainterPath(start)
    rect = QRectF(
        (arc.center.x - arc.radius) * CM_TO_SCENE,
        -(arc.center.y + arc.radius) * CM_TO_SCENE,
        arc.radius * 2 * CM_TO_SCENE,
        arc.radius * 2 * CM_TO_SCENE,
    )
    qt_start, qt_sweep = _qt_arc_angles(arc)
    path.arcTo(rect, qt_start, qt_sweep)
    return path


def _qt_arc_angles(arc: ArcSegment) -> tuple[float, float]:
    start_angle = math.degrees(math.atan2(arc.p_start.y - arc.center.y, arc.p_start.x - arc.center.x))
    sweep = math.degrees(arc.angle_rad)
    if arc.turn == Turn.CW:
        sweep = -sweep
    return start_angle, sweep


def _draw_corner_markers(scene: QGraphicsScene, solution: CourseSolution) -> None:
    pen = QPen(QColor("#d0472f"), 1.2)
    brush = QBrush(QColor(208, 71, 47, 105))

    for marker in solution.corner_markers:
        item = scene.addPolygon(_marker_polygon(marker), pen, brush)
        item.setZValue(26)
        item.setToolTip(
            "Corner marker "
            f"{marker.boundary_index}: center=({marker.center.x:.2f}, {marker.center.y:.2f}) cm, "
            f"tangent angle={marker.tangent_angle_deg:.1f} deg"
        )

        label_pos = to_scene(marker.center)
        label = QGraphicsSimpleTextItem(f"M{marker.boundary_index}")
        label.setBrush(QBrush(QColor("#a83224")))
        label.setFont(QFont("Arial", 8))
        label.setPos(label_pos.x() + 5, label_pos.y() + 5)
        label.setZValue(27)
        scene.addItem(label)


def _draw_start_goal_markers(scene: QGraphicsScene, solution: CourseSolution) -> None:
    if solution.start_goal_segment is not None:
        segment = solution.start_goal_segment
        pen = QPen(QColor("#228a63"), 1.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        a = to_scene(segment.p_start)
        b = to_scene(segment.p_end)
        item = scene.addLine(a.x(), a.y(), b.x(), b.y(), pen)
        item.setZValue(24)
        item.setToolTip(
            "Start/Goal segment: "
            f"center=({segment.center.x:.2f}, {segment.center.y:.2f}) cm, "
            f"length={segment.length:.1f} cm"
        )

    pen = QPen(QColor("#16835b"), 1.3)
    brush = QBrush(QColor(22, 131, 91, 125))

    for marker in solution.start_goal_markers:
        item = scene.addPolygon(_marker_polygon(marker), pen, brush)
        item.setZValue(28)
        item.setToolTip(
            "Start/Goal marker "
            f"{marker.marker_index}: center=({marker.center.x:.2f}, {marker.center.y:.2f}) cm, "
            f"tangent angle={marker.tangent_angle_deg:.1f} deg"
        )

        label_pos = to_scene(marker.center)
        label = QGraphicsSimpleTextItem(f"SG{marker.marker_index}")
        label.setBrush(QBrush(QColor("#0d6b49")))
        label.setFont(QFont("Arial", 8))
        label.setPos(label_pos.x() + 5, label_pos.y() + 5)
        label.setZValue(29)
        scene.addItem(label)


def _marker_polygon(marker: CornerMarker) -> QPolygonF:
    tangent_angle = math.radians(marker.tangent_angle_deg)
    normal_angle = math.radians(marker.normal_angle_deg)
    tangent = Vec2(math.cos(tangent_angle), math.sin(tangent_angle))
    normal = Vec2(math.cos(normal_angle), math.sin(normal_angle))
    half_short = marker.short_side_cm / 2.0
    half_long = marker.long_side_cm / 2.0

    points = [
        marker.center - normal * half_long - tangent * half_short,
        marker.center + normal * half_long - tangent * half_short,
        marker.center + normal * half_long + tangent * half_short,
        marker.center - normal * half_long + tangent * half_short,
    ]
    return QPolygonF([to_scene(point) for point in points])


def _draw_helper_connections(scene: QGraphicsScene, model: CourseModel) -> None:
    if len(model.circles) < 2:
        return
    pen = QPen(QColor("#7c8796"), 1.0)
    pen.setStyle(Qt.PenStyle.DashLine)
    for i, circle in enumerate(model.circles):
        next_circle = model.circles[(i + 1) % len(model.circles)]
        a = to_scene(circle.center)
        b = to_scene(next_circle.center)
        item = scene.addLine(a.x(), a.y(), b.x(), b.y(), pen)
        item.setZValue(4)


def _draw_helper_circles(scene: QGraphicsScene, model: CourseModel, on_circle_changed) -> None:
    for index, circle in enumerate(model.circles):
        item = HelperCircleItem(circle, on_circle_changed)
        scene.addItem(item)

        center = to_scene(circle.center)
        center_item = scene.addEllipse(center.x() - 3, center.y() - 3, 6, 6, QPen(QColor("#315a9e")), QBrush(QColor("#315a9e")))
        center_item.setZValue(12)

        label = QGraphicsSimpleTextItem(f"{index}: {circle.turn.value.upper()} R{circle.r:g}")
        label.setBrush(QBrush(QColor("#243044")))
        label.setFont(QFont("Arial", 9))
        label.setPos(center.x() + 7, center.y() + 7)
        label.setZValue(13)
        scene.addItem(label)


def _draw_start_goal_hint(scene: QGraphicsScene, model: CourseModel) -> None:
    p = to_scene(model.start_goal_hint.center)
    pen = QPen(QColor("#e0643b"), 1.4)
    scene.addLine(p.x() - 8, p.y(), p.x() + 8, p.y(), pen).setZValue(30)
    scene.addLine(p.x(), p.y() - 8, p.x(), p.y() + 8, pen).setZValue(30)
    label = QGraphicsSimpleTextItem("SG")
    label.setBrush(QBrush(QColor("#b94724")))
    label.setPos(p.x() + 9, p.y() + 2)
    label.setZValue(31)
    scene.addItem(label)
