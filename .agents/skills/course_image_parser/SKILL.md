---
name: course_image_parser
description: "Use when analyzing robotrace course diagram images in this repository to determine board contour, board size, start/goal candidates, a centerline point sequence, and line/arc plus helper-circle CAD JSON candidates."
---

# Course Image Parser

Use this skill in the `robotrace_course_cad` repository when the user wants to read course diagram images such as `data/*.png` and needs a robust first-stage workflow for:

- board contour detection and normalization
- board size identification
- start/goal candidate detection
- centerline mask extraction and point-sequence tracing
- line/arc fitting and helper-circle CAD JSON candidate generation
- cross-checking scripted detections against image text and visual evidence

This skill covers the scripted path through first-pass line/arc fitting and Course CAD-readable helper-circle JSON candidate generation. Manual geometry repair, final helper-circle editing, and final race-ready JSON approval remain review steps after the generated artifacts are inspected.

## Stop Rule

After finishing board analysis, start/goal analysis, centerline point-sequence extraction, line/arc fitting, and helper-circle CAD JSON candidate generation described below, stop and ask the user how to proceed.

Do not continue to manual helper-circle repair, turn-direction changes, coordinate completion, or final JSON approval unless the user explicitly instructs you to continue after reviewing the generated artifacts.

## Environment

From the repository root, prepare the dedicated image-parsing environment if needed.

```bash
uv sync --project course_image_parser
```

Run the analysis tools from the repository root so relative `data/` and `tmp/` paths stay stable.

## Workflow

### 1. Inspect inputs and current artifacts

Identify the target image or image set, then check whether related artifacts already exist.

Look for:

- the source image under `data/`
- a sidecar JSON with known board size, if any
- existing `*_notes.md` files for prior human corrections
- existing outputs under `tmp/extracted_course_boards*` or `tmp/start_goal_detection*`

If the user requested multiple images, decide whether to run them one by one or in batch, but still review findings per image.

### 2. Determine board contour and normalized board image

First obtain a script-based board hypothesis.

```bash
uv run --project course_image_parser python course_image_parser/extract_course_board.py data/<name>.png
```

Use script outputs such as:

- normalized board image
- detected board corners
- board color choice
- estimated board size
- grid period and line positions
- detection report

Then perform AI image analysis on the original image and the normalized result.

Check for visual evidence that supports or contradicts the scripted result:

- outer board frame
- panel seams and panel count
- coordinate axes or dimension labels
- visible grid spacing
- whether the detected corners actually align with the board boundary
- whether the normalized board preserves the expected rectangular geometry

When identifying board size, combine the scripted estimate with image evidence such as:

- explicit width and height labels
- coordinate-range labels
- known board cell dimensions such as 135 x 90 cm or 180 x 90 cm panels
- whether all course elements fit naturally inside the interpreted board

If the script output and visual evidence disagree, do not force a single answer silently. Present the competing interpretations, explain the mismatch, and ask the user which board interpretation should be treated as authoritative.

### 3. Generate start/goal candidates from the normalized board

After the board geometry is good enough to use, obtain a scripted start/goal hypothesis.

```bash
uv run --project course_image_parser python course_image_parser/detect_start_goal_area.py data/<name>.png
```

Treat the scripted detector as a candidate generator, not as the final authority.

Use its outputs to narrow the search space:

- top-ranked candidate segments
- candidate orientation
- marker-center positions
- candidate bounding boxes
- normalized board image with candidate overlays
- template images and score report

### 4. Cross-check start/goal candidates with AI image analysis

For the top candidates, inspect both the full image and focused crops around each candidate.

Use AI image analysis to look for:

- `START`, `GOAL`, or `START/GOAL` text
- coordinate labels near the start/goal area
- marker-like rectangles near the candidate line ends
- a straight segment close to 100 cm long
- entry direction implied by text placement, coordinates, or surrounding course flow
- whether the candidate is near a practical board edge location for race operation

Evaluate the start-area travel direction explicitly instead of assuming it from the text order alone.

- Separate these two questions:
	- which endpoint is labeled `START` and which is labeled `GOAL`
	- which direction the robot actually travels immediately after leaving `START`
- Do not assume that the course direction runs `START -> GOAL` along the marked segment.
- The correct departure direction is always the direction that leaves `START` toward the `GOAL -> START` side of the marked segment.
- Use the neighboring course geometry to decide the departure direction from `START`; the black line connected to the `START` side is more authoritative than the apparent reading order of the text.
- When coordinates are shown for both `START` and `GOAL`, compare the labeled positions with the continuation of the course on both sides of the segment and confirm that the adopted travel direction leaves `START` toward the `GOAL -> START` side.

The scripted detector should reduce the amount of image that needs close inspection. Start from the top-scoring candidates, expand the crop with a generous margin, and read nearby text or symbols before scanning the whole image again.

When image text is visible, compare the text-derived interpretation against the scripted candidate:

- if text gives explicit coordinates, compare them against the candidate segment position after normalization
- if text gives `START` and `GOAL`, determine the endpoint labels first, then separately determine the departure direction from `START`
- if a provisional read suggests `START -> GOAL`, correct it: the adopted travel direction must still leave `START` in the `GOAL -> START` direction, and the note should record that the initial read was rejected
- if marker positions are visible, compare them with the expected side of the detected segment
- if text and geometry disagree, record the disagreement explicitly instead of collapsing them into one answer

When text is weak, partially occluded, or absent, use a confidence statement such as:

- script and image agree strongly
- script geometry is plausible but text evidence is weak
- image text suggests a different location than the scripted top candidate
- multiple candidates remain viable

### 5. Extract a centerline mask and point sequence

Only do this step after one board interpretation and one start/goal interpretation are good enough to use as inputs.

Run the point-tracing script with confirmed `START` and `GOAL` coordinates.

```bash
uv run --project course_image_parser python course_image_parser/trace_centerline_points.py data/<name>.png --start-cm <start_x>,<start_y> --goal-cm <goal_x>,<goal_y>
```

Treat this as a structured first-pass centerline extraction, not as final geometry truth.

The expected mask-generation and tracing behavior is:

- start from the normalized board image
- extract dark line pixels while excluding colored overlays such as cyan, magenta, and yellow using HSV-based filtering
- clean the line mask with the current default morphology sequence
	- opening side: `open-erode-size=5`, `open-dilate-size=5`
	- closing side: `close-dilate-size=5`, `close-erode-size=5`
- thin the cleaned mask to a one-pixel-like skeleton
- place a virtual line tracer at `START`
- initialize the departure direction from the confirmed `GOAL -> START` side of the start/goal segment
- when the next point is not found at `1cm ± ε`, retry at `2cm ± ε`, then `3cm ± ε`, up to `5cm ± ε`
- at each retry distance, keep the heading constraint and prefer the candidate whose direction is closest to the current tracer heading
- update heading from a weighted fit of the most recent 5 points, with newer points weighted more strongly
- before 5 actual points exist, seed the fit history with virtual points extending backward along the `GOAL -> START` direction
- include the confirmed `START` point as the first TSV point if it is not already present
- include the confirmed `GOAL` point as the last TSV point if it is not already present
- write board dimensions, confirmed endpoints, and endpoint-insertion flags to the trace report

Inspect the generated artifacts:

- raw line mask
- cleaned line mask
- skeleton mask
- trace overlay on the normalized image
- traced point list TSV
- trace report JSON

If the trace fails to reach the goal or visibly leaves the line, do not silently start broad parameter exploration. Report where and how it failed, then ask the user before changing tracing or morphology parameters beyond the current confirmed defaults.

### 6. Fit line/arc path and generate helper-circle CAD JSON

If the board interpretation, start/goal interpretation, and centerline trace look acceptable, continue automatically to line/arc fitting.

```bash
uv run --project course_image_parser python course_image_parser/line_arc_path_fitting.py tmp/centerline_trace/<name>/trace_points.tsv --write-svg
```

If the trace was written to a non-default output directory, use that TSV path instead.

The fitting script automatically reads the sibling `report.json` for:

- confirmed `START` / `GOAL` coordinates
- board width and height
- start/goal hint information for the CAD JSON

Expected fitting behavior:

- preprocess by duplicate removal and 2 cm resampling
- build split candidates from RDP, curvature, neighboring points, and spacing constraints
- solve a tangent-aware DAG over segment hypotheses
- constrain any segment starting at the first point or ending at the final point to lie on the confirmed `START`-`GOAL` line
- keep tangent mismatch free below `3 deg`, strongly penalize mismatch above `5 deg`, and hard-reject transitions at `10 deg` or above by default
- penalize segments at or below the preferred `8 cm` threshold without hard-rejecting them by default
- fit arc candidates with radii `R10 cm` or larger in `5 cm` increments
- for each quantized radius, compute the two possible centers from the interval endpoints and choose the center with the smallest radius residual

Expected outputs:

- `line_arc_segments.json`: fitted line/arc segment model with diagnostics
- `line_arc_segments.tsv`: tabular segment list
- `line_arc_connections.tsv`: tangent mismatch report at adopted segment joints
- `line_arc_segments.svg`: debug visualization
- `course_cad_model.json`: Course CAD-readable helper-circle candidate model

Read the SVG as follows:

- pale gray polyline: traced source points
- blue dots: candidate split points
- green segments: adopted line segments
- orange segments: adopted arc segments
- short black strokes: segment endpoint tangents
- yellow/red joint dots: nonzero tangent mismatch; hover in a browser to see the angle

### 7. Review helper-circle CAD JSON

The fitting script writes `course_cad_model.json` by converting each fitted arc to a helper circle.

Default helper-circle behavior:

- `clockwise=True` arcs become `turn: "cw"`
- counterclockwise arcs become `turn: "ccw"`
- `start_goal_hint` is generated from the confirmed `START` / `GOAL` midpoint and length
- board dimensions come from the trace report when available
- helper-circle postprocessing is enabled by default

The helper-circle postprocessing is intentionally applied only to the CAD JSON, not to the line/arc debug outputs.

For consecutive arc runs, postprocessing does the following:

- treat the first circle in a run as fixed
- apply Fit Touch-equivalent center adjustment sequentially to 1-based positions `2, 3, 4, ..., N-1`
- apply Fit Prev-equivalent center adjustment to the `N`th circle
- if the `N`th circle is the final helper circle in the course, place it analytically so it touches both the previous circle and the confirmed `START`-`GOAL` line
- use a tiny positive numerical slack (`1e-10 cm`) so Course CAD's tangent solver sees a zero-length-like valid tangent without creating short-tangent warnings

Disable helper-circle postprocessing only for comparison/debugging:

```bash
uv run --project course_image_parser python course_image_parser/line_arc_path_fitting.py tmp/centerline_trace/<name>/trace_points.tsv --no-adjust-touching-helper-circles
```

Validate that the generated Course CAD JSON loads and summarize solver issues:

```bash
PYTHONPATH=src python - <<'PY'
from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.solver.course_solver import solve_course

model = load_course_model("tmp/line_arc_path_fitting/<name>/course_cad_model.json")
solution = solve_course(model)
print(len(model.circles), "helper circles")
for issue in solution.issues:
    print(issue.severity, issue.message)
PY
```

Treat the generated CAD JSON as a candidate, not final truth. If Course CAD reports residual short arcs, intersections, or visually incorrect helper circles, report those issues and stop for user review.

### 8. Produce a user-facing intermediate report

Before any manual repair or final JSON approval, summarize the current state for each image.

Report at least:

- interpreted board size and why
- whether board contour detection looked reliable
- top 1 to 3 start/goal candidates
- evidence used for each candidate
- endpoint labeling and the chosen departure direction from `START`
- whether the centerline trace reached the goal
- whether the trace overlay visually stays on the course centerline
- any mismatches between scripted detection and image text reading
- what remains uncertain

When available, point the user to generated artifacts such as:

- normalized board image
- board-detection report
- start/goal candidate overlay
- start/goal report JSON
- centerline trace overlay
- centerline point TSV
- centerline trace report JSON
- line/arc fit JSON, TSV, connection TSV, and SVG
- Course CAD-readable `course_cad_model.json`
- Course CAD solver issue summary

### 9. Mandatory pause

Stop after reporting the fitted line/arc and helper-circle CAD JSON findings.

Ask the user whether to:

1. accept one board interpretation and one start/goal candidate
2. accept the current centerline point sequence or review its failure points
3. review ambiguous candidates together
4. review or manually repair the generated helper-circle CAD JSON

Do not continue automatically past this checkpoint.

## Validation Checklist

Before stopping, make sure all of the following are true:

- board contour was checked by both script output and visual inspection
- board size was justified by either explicit image evidence or a clearly stated inference
- start/goal candidates were generated from the scripted detector
- AI image analysis was used to inspect candidate regions, not only the whole image
- any visible text or coordinate labels were compared against the scripted candidates
- the centerline mask excluded colored overlay lines before morphology
- the tracer used the confirmed `GOAL -> START` departure direction at `START`
- the traced TSV includes the confirmed `START` and `GOAL` as first and last points after endpoint insertion
- the centerline trace outcome was reviewed in overlay form, not only by numeric report
- arc radii in `line_arc_segments.json` are `R10 cm` or larger and multiples of `5 cm` unless `--no-quantize-arc-radius` was used
- start-touching and goal-touching candidate segments were constrained to the confirmed `START`-`GOAL` line
- `course_cad_model.json` loads with `load_course_model`
- Course CAD solver issues were summarized, especially `No tangent candidate`, short tangent, short arc, and intersection messages
- helper-circle Fit Touch postprocessing was left enabled unless the user requested a comparison
- unresolved conflicts were reported to the user
- the workflow stopped before manual helper-circle repair or final JSON approval

## Notes

- Prefer the dedicated `course_image_parser` environment over the CAD runtime environment for image-analysis work.
- If multiple batch results exist, compare them consistently per image rather than mixing outputs from different runs.
- If a prior `*_notes.md` file exists and the user provides corrections, update that notes file before moving to any later stage.
- The scripted workflow ends after line/arc fitting and helper-circle CAD JSON candidate generation. Continue to manual geometry repair or final JSON approval only after user review.
