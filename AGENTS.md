# AGENTS

## Purpose

Robotrace Course CAD is a small PySide6 desktop CAD tool for designing robotrace courses by editing helper circles and deriving centerline geometry from them.

## Setup and Run

- Python 3.10+ and `uv` are the expected local tools.
- Preferred setup from the repo root:

```bash
uv venv
uv pip install -e .
```

- Start the app with the installed entry point:

```bash
robotrace-course-cad
robotrace-course-cad examples/synthetic/2025alljapan.json
```

- On Linux, `./run_robotrace_course_cad.sh` is the supported bootstrap script. It creates `.venv` if missing, reinstalls editable deps, then launches the app.

## Validation

- The test suite uses `unittest`, not `pytest`.
- For headless runs, always set `QT_QPA_PLATFORM=offscreen`.
- Preferred full test command on Linux:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

- For narrow validation, run the touched test module with the same environment, for example:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest tests.test_main
```

## Architecture

- Keep the core split intact: `CourseModel` is editable source data, `solve_course()` derives a `CourseSolution`, and UI/render/export consume that derived solution.
- Put geometry and validation behavior in `src/robotrace_course_cad/solver/`, not in Qt widgets.
- Keep JSON load/save behavior in `src/robotrace_course_cad/io/json_io.py`.
- Keep rendering and export concerns in `src/robotrace_course_cad/render/`.
- Treat `src/robotrace_course_cad/ui/` as orchestration around model edits, solver refreshes, and scene updates.

## Project Conventions

- Units are centimeters in the design/model layer.
- Internal coordinates follow math coordinates: positive `x` to the right, positive `y` upward. Only convert to screen coordinates in Qt rendering.
- Avoid storing authoritative design state in `QGraphicsItem` objects. The spec explicitly keeps design data separate from scene items.
- Preserve the typed, dataclass-heavy style already used across `model/`, `solver/`, and `io/`.
- Surface geometry problems through `CourseSolution.issues` when possible instead of hiding them in UI-only messages.

## PySide6 Caveats

- Tests and utilities that touch Qt should reuse `QApplication.instance()` when possible.
- On Ubuntu/WSL, missing Qt runtime packages can break startup. See the README troubleshooting notes for `libxcb-cursor0` and `QT_QPA_PLATFORM=xcb`.
- The app intentionally applies a light Fusion theme in `src/robotrace_course_cad/main.py`; keep UI changes compatible with that baseline unless the task is explicitly about theming.

## Key Files

- [README.md](README.md): setup, launch commands, troubleshooting, and manual usage.
- [doc/robotrace_course_cad_spec.md](doc/robotrace_course_cad_spec.md): domain rules, coordinate system, and the intended model/solution/render separation.
- [doc/tips.md](doc/tips.md): course-design workflow notes for patterns such as chicanes and S-curves.
- [src/robotrace_course_cad/model/course_model.py](src/robotrace_course_cad/model/course_model.py): primary editable domain model.
- [src/robotrace_course_cad/solver/course_solver.py](src/robotrace_course_cad/solver/course_solver.py): top-level derived-geometry pipeline.
- [tests/](tests/): canonical behavior checks for JSON I/O, solver geometry, markers, export, and Qt startup.

## Working Notes for Agents

- Prefer minimal, local fixes in the owning layer instead of patching around behavior in the UI.
- If a change affects generated geometry, check both solver tests and any export/reference tests that cover the same behavior.
- Link to repo docs instead of copying large design explanations into new instruction files.