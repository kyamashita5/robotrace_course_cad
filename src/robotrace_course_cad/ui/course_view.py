from __future__ import annotations

from PySide6.QtGui import QPainter, QWheelEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


class CourseView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(0.55, 0.55)

    def wheelEvent(self, event: QWheelEvent) -> None:
        mouse_pos = event.position().toPoint()
        scene_pos_before = self.mapToScene(mouse_pos)

        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

        scene_pos_after = self.mapToScene(mouse_pos)
        delta = scene_pos_after - scene_pos_before
        self.horizontalScrollBar().setValue(round(self.horizontalScrollBar().value() + delta.x()))
        self.verticalScrollBar().setValue(round(self.verticalScrollBar().value() + delta.y()))
        event.accept()
