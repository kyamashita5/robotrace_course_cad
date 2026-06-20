---
name: robotrace-synthetic-reference
description: Use when adding Robotrace Course CAD course JSON files to examples/synthetic and generating examples/synthetic_reference from the current solver/CAD output, then validating the synthetic reference tests.
---

# Robotrace Synthetic Reference

Use this skill in the `robotrace_course_cad` repository when the user asks to add course `.json` files from `data/` or another location into `examples/synthetic/` and create matching reference files under `examples/synthetic_reference/`.

The reference is treated as the current implementation's truth:

- `*_helper_circles.json` comes from the course model's helper circles.
- `*_arcs.json` and `*_tangents.json` come from `solve_course(model)`.
- Existing synthetic tests compare the generated arcs/tangents against these reference files.

## Workflow

1. Inspect inputs and current state.

```bash
rg --files data examples/synthetic examples/synthetic_reference | sort
git status --short
```

2. Generate examples and reference files with the bundled script.

Pass course names without `.json`; each name must exist as `data/<name>.json` unless `--source-dir` is specified.

```bash
PYTHONPATH=src .venv/bin/python skills/robotrace-synthetic-reference/scripts/generate_synthetic_reference.py 2023kansai 2024kansai 2025kansai
```

The script copies each input JSON to `examples/synthetic/<name>.json`, solves it, and writes:

- `examples/synthetic_reference/<name>_helper_circles.json`
- `examples/synthetic_reference/<name>_arcs.json`
- `examples/synthetic_reference/<name>_tangents.json`

It fails if the solver reports any `error` severity issue.

3. Run tests.

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest tests.test_synthetic_reference
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover
```

4. Confirm the diff only contains intended files.

```bash
git status --short
git diff -- examples/synthetic examples/synthetic_reference
```

## Checks To Report

In the final response, include:

- course names added to `examples/synthetic`
- counts of helpers/arcs/tangents generated for each course
- test results
- any solver errors or unexpected diffs

## Notes

- Do not manually edit reference numeric values; regenerate from the current solver output.
- Do not update reference files for grid or start/goal changes alone unless arcs/tangents/helper circles changed.
- Preserve unrelated user changes in the worktree.
