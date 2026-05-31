from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsScene,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from robotrace_course_cad.model.course_model import CourseModel, HelperCircle, Turn
from robotrace_course_cad.render.qt_renderer import render_course
from robotrace_course_cad.solver.course_solver import solve_course
from robotrace_course_cad.ui.course_view import CourseView


class MainWindow(QMainWindow):
    def __init__(self, model: CourseModel):
        super().__init__()
        self.model = model
        self.solution = solve_course(model)
        self._updating_table = False

        self.setWindowTitle("Robotrace Course CAD")
        self.scene = QGraphicsScene(self)
        self.view = CourseView(self.scene)
        self.table = QTableWidget(0, 5)
        self.sg_x = _spin(-10000, 10000, self.model.start_goal_hint.x)
        self.sg_y = _spin(-10000, 10000, self.model.start_goal_hint.y)
        self.sg_length = _spin(1, 10000, self.model.start_goal_hint.length)
        self.issue_label = QLabel()
        self.issue_label.setWordWrap(True)

        self._build_ui()
        self._connect()
        self.refresh_all()

    def _build_ui(self) -> None:
        add_button = QPushButton("Add")
        delete_button = QPushButton("Delete")
        up_button = QPushButton("Up")
        down_button = QPushButton("Down")
        self.add_button = add_button
        self.delete_button = delete_button
        self.up_button = up_button
        self.down_button = down_button

        self.table.setHorizontalHeaderLabels(["ID", "X cm", "Y cm", "R cm", "Turn"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        controls = QHBoxLayout()
        for button in (add_button, delete_button, up_button, down_button):
            controls.addWidget(button)

        form = QFormLayout()
        form.addRow("SG X cm", self.sg_x)
        form.addRow("SG Y cm", self.sg_y)
        form.addRow("SG length cm", self.sg_length)

        side = QVBoxLayout()
        side.addWidget(QLabel("Helper Circles"))
        side.addWidget(self.table, 1)
        side.addLayout(controls)
        side.addSpacing(10)
        side.addWidget(QLabel("Start / Goal Hint"))
        side.addLayout(form)
        side.addSpacing(10)
        side.addWidget(QLabel("Solver Messages"))
        side.addWidget(self.issue_label)

        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setMinimumWidth(360)

        root = QHBoxLayout()
        root.addWidget(self.view, 1)
        root.addWidget(side_widget)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

    def _connect(self) -> None:
        self.add_button.clicked.connect(self.add_circle)
        self.delete_button.clicked.connect(self.delete_selected_circle)
        self.up_button.clicked.connect(lambda: self.move_selected_circle(-1))
        self.down_button.clicked.connect(lambda: self.move_selected_circle(1))
        self.table.cellChanged.connect(self.on_table_cell_changed)
        self.sg_x.valueChanged.connect(self.on_start_goal_changed)
        self.sg_y.valueChanged.connect(self.on_start_goal_changed)
        self.sg_length.valueChanged.connect(self.on_start_goal_changed)

    def refresh_all(self) -> None:
        self.solution = solve_course(self.model)
        self.populate_table()
        self.refresh_scene()
        self.refresh_issues()

    def refresh_scene(self) -> None:
        render_course(self.scene, self.model, self.solution, self.on_circle_dragged)

    def populate_table(self) -> None:
        self._updating_table = True
        self.table.setRowCount(len(self.model.circles))
        for row, circle in enumerate(self.model.circles):
            self.table.setItem(row, 0, _readonly_item(str(circle.id)))
            self.table.setItem(row, 1, _number_item(circle.x))
            self.table.setItem(row, 2, _number_item(circle.y))
            self.table.setItem(row, 3, _number_item(circle.r))
            combo = QComboBox()
            combo.addItems(["CCW", "CW"])
            combo.setCurrentText(circle.turn.value.upper())
            combo.currentTextChanged.connect(lambda _text, r=row: self.on_turn_changed(r))
            self.table.setCellWidget(row, 4, combo)
        self._updating_table = False

    def refresh_issues(self) -> None:
        if not self.solution.issues:
            self.issue_label.setText("No solver messages.")
            return
        self.issue_label.setText("\n".join(f"{issue.severity.upper()}: {issue.message}" for issue in self.solution.issues))

    def add_circle(self) -> None:
        if self.model.circles:
            last = self.model.circles[-1]
            x = last.x + 40.0
            y = last.y
            r = last.r
            turn = Turn.CCW if last.turn == Turn.CW else Turn.CW
        else:
            x = y = 0.0
            r = self.model.radius_presets_cm[0] if self.model.radius_presets_cm else 20.0
            turn = Turn.CCW
        self.model.circles.append(HelperCircle(self.model.next_circle_id(), x, y, r, turn))
        self.refresh_all()
        self.table.selectRow(len(self.model.circles) - 1)

    def delete_selected_circle(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self.model.circles):
            del self.model.circles[row]
            self.refresh_all()
            self.table.selectRow(min(row, len(self.model.circles) - 1))

    def move_selected_circle(self, delta: int) -> None:
        row = self.table.currentRow()
        new_row = row + delta
        if 0 <= row < len(self.model.circles) and 0 <= new_row < len(self.model.circles):
            self.model.circles[row], self.model.circles[new_row] = self.model.circles[new_row], self.model.circles[row]
            self.refresh_all()
            self.table.selectRow(new_row)

    def on_table_cell_changed(self, row: int, column: int) -> None:
        if self._updating_table or row >= len(self.model.circles):
            return
        circle = self.model.circles[row]
        try:
            if column == 1:
                circle.x = float(self.table.item(row, column).text())
            elif column == 2:
                circle.y = float(self.table.item(row, column).text())
            elif column == 3:
                circle.r = max(0.1, float(self.table.item(row, column).text()))
            else:
                return
        except ValueError:
            self.populate_table()
            return
        self.refresh_all()
        self.table.selectRow(row)

    def on_turn_changed(self, row: int) -> None:
        if self._updating_table or row >= len(self.model.circles):
            return
        combo = self.table.cellWidget(row, 4)
        self.model.circles[row].turn = Turn.from_value(combo.currentText())
        self.refresh_all()
        self.table.selectRow(row)

    def on_start_goal_changed(self) -> None:
        self.model.start_goal_hint.x = self.sg_x.value()
        self.model.start_goal_hint.y = self.sg_y.value()
        self.model.start_goal_hint.length = self.sg_length.value()
        self.solution = solve_course(self.model)
        self.refresh_scene()
        self.refresh_issues()

    def on_circle_dragged(self, circle: HelperCircle) -> None:
        self.solution = solve_course(self.model)
        self.populate_table()
        self.refresh_scene()
        self.refresh_issues()


def _number_item(value: float) -> QTableWidgetItem:
    item = QTableWidgetItem(f"{value:.3f}".rstrip("0").rstrip("."))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _readonly_item(value: str) -> QTableWidgetItem:
    item = QTableWidgetItem(value)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def _spin(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(2)
    spin.setSingleStep(5.0)
    spin.setValue(value)
    return spin
