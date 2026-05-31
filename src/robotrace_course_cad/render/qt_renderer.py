from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsSimpleTextItem

from robotrace_course_cad.model.course_model import CourseModel, HelperCircle, Turn
from robotrace_course_cad.model.course_solution import ArcSegment, CourseSolution
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
    scene.setSceneRect(QRectF(-2200, -1400, 4400, 2800))
    _draw_grid(scene)
    _draw_generated_line(scene, model, solution)
    _draw_helper_connections(scene, model)
    _draw_helper_circles(scene, model, on_circle_changed)
    _draw_start_goal_hint(scene, model)


def _draw_grid(scene: QGraphicsScene) -> None:
    light = QPen(QColor("#eceff3"), 0)
    axis = QPen(QColor("#c8ced8"), 0)
    for cm in range(-200, 201, 10):
        pen = axis if cm == 0 else light
        x = cm * CM_TO_SCENE
        y = cm * CM_TO_SCENE
        scene.addLine(x, -1400, x, 1400, pen)
        scene.addLine(-2200, y, 2200, y, pen)


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
