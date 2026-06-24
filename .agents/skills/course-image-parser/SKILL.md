---
name: course-image-parser
description: "Use when analyzing robotrace course diagram images in this repository to determine board contour, board size, start/goal candidates, a centerline point sequence, and line/arc plus helper-circle CAD JSON candidates."
---

# Course Image Parser

Use this skill in the `robotrace_course_cad` repository when the user wants to read course diagram images such as `data/*.png` and needs a robust first-stage workflow for:

- board contour detection and normalization
- board size identification
- start/goal candidate detection
- centerline mask extraction and point-sequence tracing
- line/arc fitting and helper-circle sequence extraction
- support-circle and R50/60 slalom candidate detection
- AI-assisted OCR of red drawing annotations only
- matching line-trace arc geometry against extracted helper-circle candidates
- generating corrected helper-circle CAD JSON candidates
- scripted consolidation of OCR text with support-circle and slalom detections

This skill covers the scripted path through first-pass line/arc fitting, support-circle/slalom candidate detection, AI-assisted red-text OCR, scripted consolidation of that OCR with detected design candidates, matching those candidates back to the traced arc sequence, and generating a corrected Course CAD-readable helper-circle JSON candidate. Manual geometry repair, final helper-circle editing, and final race-ready JSON approval remain review steps after the generated artifacts are inspected.

## Stop Rule

After finishing board analysis, start/goal analysis, centerline point-sequence extraction, line/arc fitting, support-circle/slalom detection, red-text OCR, scripted design-candidate consolidation, line-arc-to-candidate matching, and corrected helper-circle CAD JSON generation described below, stop and ask the user how to proceed.

Do not continue to manual helper-circle repair, turn-direction changes, coordinate completion, or final JSON approval unless the user explicitly instructs you to continue after reviewing the generated artifacts.

The corrected JSON produced by `correct_helper_circles_from_matches.py` is the artifact to provide for review even if Course CAD reports `No tangent candidate`, short tangents, short arcs, intersections, or other solver issues. Report those issues and ask the user how to proceed. Do not replace that script output with `line_arc_path_fitting/<name>/course_cad_model.json`, a no-touch-adjust line-trace JSON, or any other line-trace-only converted/corrected JSON. Never present line-trace-only geometry as the final candidate for this workflow.

## Environment

From the repository root, prepare the dedicated image-parsing environment if needed.

```bash
uv sync --project course_image_parser
```

Run the analysis tools from the repository root so relative `data/` and `tmp/` paths stay stable.

## Output Layout

Keep all intermediate outputs for one course under `tmp/<name>/`.

Use stage-specific subdirectories below that course directory:

- `tmp/<name>/extracted_course_boards/<name>/`
- `tmp/<name>/start_goal_detection/<name>/`
- `tmp/<name>/centerline_trace/<name>/`
- `tmp/<name>/line_arc_path_fitting/<name>/`
- `tmp/<name>/support_circle_detection/<name>/`
- `tmp/<name>/slalom_template_detection/<name>/`
- `tmp/<name>/line_design_info_extraction/`
- `tmp/<name>/consolidated_design_candidates/<name>/`
- `tmp/<name>/helper_circle_matching/<run_name>/`
- `tmp/<name>/helper_circle_correction/<run_name>/`

When a script has both `--out-dir` and `--name`, keep `--name <name>` for image-derived stages so shared board-normalization lookup remains consistent, and set `--out-dir` to the stage parent under `tmp/<name>/`.

## Workflow

### 1. Inspect inputs and current artifacts

Identify the target image or image set, then check whether related artifacts already exist.

Look for:

- the source image under `data/`
- a sidecar JSON with known board size, if any
- existing `*_notes.md` files for prior human corrections
- existing outputs under `tmp/<name>/`

If the user requested multiple images, decide whether to run them one by one or in batch, but still review findings per image.

### 2. Determine board contour and normalized board image

First obtain a script-based board hypothesis.

```bash
uv run --project course_image_parser python course_image_parser/extract_course_board.py \
  data/<name>.png \
  --out-dir tmp/<name>/extracted_course_boards \
  --name <name>
```

Use script outputs such as:

- normalized board image
- detected board corners
- board color choice
- estimated board size
- adopted board-size hypothesis in `report.json` under `board_size_hypothesis`
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

Read `tmp/<name>/extracted_course_boards/<name>/report.json` after this step. When `board_size_hypothesis.source` is `"grid_cell_size_hypothesis"`, treat `board_size_hypothesis.selected_cell_cm` as the adopted board-grid cell size for later Course CAD JSON generation unless visual review rejects that board interpretation. Record the selected cell size alongside the board dimensions in your notes.

If the script output and visual evidence disagree, do not force a single answer silently. Present the competing interpretations, explain the mismatch, and ask the user which board interpretation should be treated as authoritative.

### 3. Generate start/goal candidates from the normalized board

After the board geometry is good enough to use, obtain a scripted start/goal hypothesis.

```bash
uv run --project course_image_parser python course_image_parser/detect_start_goal_area.py \
  data/<name>.png \
  --out-dir tmp/<name>/start_goal_detection \
  --board-out-dir tmp/<name>/extracted_course_boards \
  --name <name>
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
uv run --project course_image_parser python course_image_parser/trace_centerline_points.py \
  data/<name>.png \
  --start-cm <start_x>,<start_y> \
  --goal-cm <goal_x>,<goal_y> \
  --out-dir tmp/<name>/centerline_trace \
  --board-out-dir tmp/<name>/extracted_course_boards \
  --start-goal-out-dir tmp/<name>/start_goal_detection \
  --name <name>
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

When reporting this failure, suggest `--line-mask-mode nonwhite-except-cyan` as the next targeted retry when colored or gray annotations appear to be breaking the black-line mask. Explain that this mode keeps non-white marks while removing cyan board/grid contour lines, which can preserve black-line continuity through red or gray overprint areas. Do not run this retry until the user explicitly asks for it.

### 6. Fit line/arc path and preserve arc geometry

If the board interpretation, start/goal interpretation, and centerline trace look acceptable, continue automatically to line/arc fitting.

```bash
uv run --project course_image_parser python course_image_parser/line_arc_path_fitting.py \
  tmp/<name>/centerline_trace/<name>/trace_points.tsv \
  --out-dir tmp/<name>/line_arc_path_fitting \
  --name <name> \
  --grid-cell-width-cm <selected_cell_width_cm> \
  --grid-cell-height-cm <selected_cell_height_cm> \
  --write-svg
```

If the trace was written to a non-default output directory, use that TSV path instead.

Use the `selected_cell_cm` values from `tmp/<name>/extracted_course_boards/<name>/report.json` for `--grid-cell-width-cm` and `--grid-cell-height-cm` when the adopted board-size hypothesis includes them. This is how the final Course CAD-readable JSON reflects the board hypothesis: through its ordinary `grid.cell_width_cm` and `grid.cell_height_cm` fields, not through extra metadata. If the board size came from an explicit sidecar JSON or command-line size and no `selected_cell_cm` is present, use the authoritative grid cell size from that JSON when available; otherwise keep the existing fitting defaults and report that the grid cell size was not inferred from the board extractor.

The fitting script automatically reads the sibling `report.json` for:

- confirmed `START` / `GOAL` coordinates
- board width and height
- start/goal hint information for any intermediate CAD JSON

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
- `course_cad_model.json`: intermediate Course CAD-readable helper-circle model

Read the SVG as follows:

- pale gray polyline: traced source points
- blue dots: candidate split points
- green segments: adopted line segments
- orange segments: adopted arc segments
- short black strokes: segment endpoint tangents
- yellow/red joint dots: nonzero tangent mismatch; hover in a browser to see the angle

For matching against consolidated design candidates, use `line_arc_segments.json`, not the helper-circle centers in `course_cad_model.json`.

The arc geometry in `line_arc_segments.json` records the actually used fitted arc interval: endpoints, center, radius, turn direction, angle, and length. This is the preferred source for downstream matching because large-radius partial arcs can have center/radius errors while still placing the used line segment on the correct support circle.

Do not add any early helper-circle touch correction to the line-arc fitting CAD JSON. Touch correction for the final CAD candidate is done later, after image-derived helper-circle candidates have been matched and exact/approx flags are known.

### 7. Understand the intermediate helper-circle CAD JSON

The fitting script also writes `course_cad_model.json` by converting each fitted arc to a helper circle. Treat it as an intermediate/debug CAD artifact for this workflow, not as a final deliverable or fallback result. Only use it as the ordered editable base required by `correct_helper_circles_from_matches.py`.

Default helper-circle behavior:

- `clockwise=True` arcs become `turn: "cw"`
- counterclockwise arcs become `turn: "ccw"`
- `start_goal_hint` is generated from the confirmed `START` / `GOAL` midpoint and length
- board dimensions come from the trace report when available
- no Fit Touch/Fit Prev/Fit Next-equivalent correction is applied during this JSON conversion
- helper-circle centers in `course_cad_model.json` are the fitted arc centers from `line_arc_segments.json`

Validate that an intermediate Course CAD JSON loads when it is generated, but do not treat its solver issues as final until the later matching/correction step:

```bash
PYTHONPATH=src python - <<'PY'
from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.solver.course_solver import solve_course

model = load_course_model("tmp/<name>/line_arc_path_fitting/<name>/course_cad_model.json")
solution = solve_course(model)
print(len(model.circles), "helper circles")
for issue in solution.issues:
    print(issue.severity, issue.message)
PY
```

Treat the generated CAD JSON as a debug artifact, not final truth. If Course CAD reports residual short arcs, intersections, or visually incorrect helper circles at this stage, report those issues only as context and continue to scripted support/slalom detection, OCR, consolidation, matching, and correction unless the user explicitly asks to stop here.

### 8. Detect support-circle and slalom candidates

After line/arc fitting, generate additional scripted candidates that will be consolidated with red-text OCR. Do not ask AI to accept or reject these geometry candidates; candidate filtering, scoring, and integration belong to the scripts.

Detect red/magenta support-circle annotations:

```bash
uv run --project course_image_parser python course_image_parser/detect_support_circles.py \
  data/<name>.png \
  --out-dir tmp/<name>/support_circle_detection \
  --board-out-dir tmp/<name>/extracted_course_boards \
  --name <name>
```

For focused checks, limit the candidate radii:

```bash
uv run --project course_image_parser python course_image_parser/detect_support_circles.py \
  data/<name>.png \
  --out-dir tmp/<name>/support_circle_detection \
  --board-out-dir tmp/<name>/extracted_course_boards \
  --name <name> \
  --max-radius-cm 200
```

Expected support-circle outputs under `tmp/<name>/support_circle_detection/<name>/`:

- `magenta_mask.png`: red/magenta drawing annotations extracted in HSV/RGB space
- `magenta_overlay.png`: normalized board with extracted red/magenta pixels overlaid
- `magenta_skeleton.png`
- `line_mask.png`, `line_mask_cleaned.png`, and `line_skeleton.png`
- `combined_mask.png` and `combined_skeleton.png`
- `circle_candidates.png`: detected support-circle overlay
- `circle_candidates.tsv` and `report.json`: ranked circle candidates

Use `magenta_support_count` and `line_support_count` to understand whether each candidate is supported by red drawing annotations, the black course line, or both.

Detect R50/60 cm slalom templates:

```bash
uv run --project course_image_parser python course_image_parser/detect_slalom_template.py \
  data/<name>.png \
  --out-dir tmp/<name>/slalom_template_detection \
  --board-out-dir tmp/<name>/extracted_course_boards \
  --name <name> \
  --trace-points-tsv tmp/<name>/centerline_trace/<name>/trace_points.tsv
```

Expected slalom outputs under `tmp/<name>/slalom_template_detection/<name>/`:

- `line_mask.png`: raw extracted black-line and marker mask used for matching
- `search_input.png`: template-match input image
- `template_sheet.png`: generated R50/60 slalom templates
- `slalom_candidates.png`: candidate overlay
- `slalom_candidates.tsv` and `report.json`: ranked slalom candidates

The slalom detector is intentionally permissive before postfiltering, but the normal workflow must pass `--trace-points-tsv` so trajectory post-filtering is enabled. Check `report.json` and confirm `post_filter.trajectory_filter.enabled` is `true` before using the slalom report in `consolidate_design_candidates.py`.

Important: dashed guide frames, small marker marks, and printed marker rows are normal evidence for a drawn slalom template. Do not reject a slalom candidate merely because it is surrounded by a dashed frame or includes marker-like printed elements. Those features may be exactly why the template is present in the drawing.

### 9. Extract red design text only

Use the `line-design-info-extractor` skill to perform AI-assisted OCR of red printed design information. In the later workflow, AI image recognition is used only for reading red text. Do not ask AI to decide whether support-circle candidates or slalom candidates are valid, do not ask AI to merge geometry candidates, and do not ask AI to choose the final helper-circle list. Those decisions are handled by `detect_support_circles.py`, `detect_slalom_template.py`, and `consolidate_design_candidates.py`.

Write the OCR output under `tmp/<name>/line_design_info_extraction/line_design_info.json`. This file records text hypotheses only: `circle` entries for radius/center labels and `coordinate` entries for standalone coordinate labels. It is not the consolidated helper-circle candidate list.

For each OCR entry:

- `type` is `circle` or `coordinate`
- `radius` is present only for `circle` entries and is a list of `[value, confidence]` hypotheses, or `null`
- `xy` is a list of `[[x, y], confidence]` hypotheses, or `null`
- `info_xy` is the printed text center in board centimeters for normalized images when available
- `info_xy_px` is the printed text center in pixels for non-normalized images when available
- keep multiple hypotheses when the text is ambiguous or partly occluded

Example OCR-only output:

```json
{
  "items": [
    {
      "type": "circle",
      "radius": [[15.0, 0.95]],
      "xy": [[[58.0, 220.0], 0.9]],
      "info_xy": [58.0, 220.0],
      "evidence": "R15 / 58, 220 printed in red"
    },
    {
      "type": "coordinate",
      "xy": [[[40.0, 210.0], 0.9]],
      "info_xy": [40.0, 210.0],
      "evidence": "standalone red coordinate"
    }
  ]
}
```

The OCR stage should read text, not infer geometry. Do not include `helper_circles`, `r50_60_slaloms`, `approx_radius`, or `approx_center` in `line_design_info.json`; those fields are produced later by the consolidation script.

Red support-circle text is often centered near the circle and commonly appears as:

```text
R15
58, 220
```

Small-radius circles may split the coordinate over three centered lines:

```text
R10
150,
113
```

Some support-circle annotations include only the radius. The red text is often printed at the circle center, but for layout reasons, especially with large-radius circles, it may be printed near the actual course line instead of near the geometric center. Do not assume the text position is the center; read the numeric coordinate when present.

For standalone coordinate labels, extract the coordinate even when it is near a start/goal label, a slalom endpoint, or another construction mark. The consolidation script will decide whether it matches a support circle, slalom endpoint, start/goal location, or nothing.

For R50/60 cm slalom areas, OCR only the red coordinate and radius labels visible near the pattern. The detector's `start_cm`, `end_cm`, `center_cm`, and `arc_centers_cm` are template-match coordinates, not text reads. Do not treat values such as `69.75` or `239.994` as printed coordinates. The later consolidation script gives priority to printed coordinate hypotheses when they uniquely determine slalom helper-circle centers; otherwise it uses template-derived centers as approximate values.

Course dimension annotations used here are red. Prioritize red text and red/magenta support annotations over black course geometry when extracting exact numeric values.

### 10. Consolidate design candidates

After red design text has been extracted and support-circle/slalom detections are available, build the candidate JSON for downstream matching:

```bash
uv run --project course_image_parser python course_image_parser/consolidate_design_candidates.py \
  tmp/<name>/line_design_info_extraction/line_design_info.json \
  tmp/<name>/support_circle_detection/<name>/report.json \
  --out-dir tmp/<name>/consolidated_design_candidates \
  --name <name> \
  --image-path tmp/<name>/support_circle_detection/<name>/magenta_overlay.png \
  --trace-points-tsv tmp/<name>/centerline_trace/<name>/trace_points.tsv \
  --slalom-template-report-json tmp/<name>/slalom_template_detection/<name>/report.json
```

This script is responsible for integrating OCR text with scripted support-circle and slalom detections. It chooses the best matching radius/center hypotheses, assigns `approx_radius` and `approx_center`, adds retained R50/60 slalom entries, and writes the downstream candidate JSON. AI should not overwrite or manually reconstruct this output.

Expected outputs:

- `consolidated_design_candidates.json`: downstream candidate JSON with `helper_circles` and `r50_60_slaloms`
- `consolidated_design_candidates.tsv`: flattened review table for ordinary helper circles and nested slalom helper circles
- `r50_60_slaloms.tsv`: slalom-template summary
- `detection_failures.tsv`: red text items that could not be matched to scripted detections
- `consolidated_design_candidates.png`: overlay visualization
- `summary.txt`: concise text summary

If no slalom template report is available, omit `--slalom-template-report-json`; the output should still contain an empty `r50_60_slaloms` list. If a report is available, let the script apply its rule-based postfilters and consolidation logic.

### 11. Match traced arcs to image-derived helper circles

After the consolidated design-candidate list is available, match the traced arc sequence against that list.

Use `line_arc_segments.json` as the fitted input so matching evaluates the actually used arc interval:

```bash
uv run --project course_image_parser python course_image_parser/match_helper_circles.py \
  tmp/<name>/line_arc_path_fitting/<name>/line_arc_segments.json \
  tmp/<name>/consolidated_design_candidates/<name>/consolidated_design_candidates.json \
  --out-dir tmp/<name>/helper_circle_matching \
  --name consolidated_arc_residual \
  --image-path tmp/<name>/support_circle_detection/<name>/magenta_overlay.png \
  --top-k 5
```

Do not use `course_cad_model.json` as the primary matching input for this workflow. It does not contain the full fitted arc intervals, and large-radius partial arcs are better judged by the line actually used in `line_arc_segments.json`.

Expected matching behavior:

- read each fitted `kind=="arc"` segment as one ordered fitted helper-circle entry
- sample points along the fitted arc interval
- evaluate whether those sampled points lie on each image-derived candidate circle
- read ordinary candidates from `helper_circles`, and expand `r50_60_slaloms` entries internally into three `source="slalom_template"` trajectory candidates using their nested helper circles, turns, start, and end
- report `arc_rms_error_cm` and `arc_max_error_cm` for each match
- allow multiple fitted arcs to match one image-derived candidate, such as when a large support circle is split by a chicane
- allow missing entries on either side

For arc-residual matching, radius mismatch is intentionally softer for larger radii than in center-distance matching:

- use `--arc-radius-relative-scale` to control how much fitted/candidate radius mismatch is tolerated; the current default is permissive for R50+ cases
- use `--arc-radius-weight` to keep radius mismatch as a light penalty while letting `arc_rms_error_cm` dominate
- prefer tuning these arc-specific options over lowering the global match threshold when a fitted radius is wrong but the used arc lies on the candidate circle

Review:

- `tmp/<name>/helper_circle_matching/consolidated_arc_residual/helper_circle_matches.tsv`
- `tmp/<name>/helper_circle_matching/consolidated_arc_residual/helper_circle_matches.json`
- `tmp/<name>/helper_circle_matching/consolidated_arc_residual/helper_circle_matches.png`

The visualization uses solid circles for fitted helper circles, dashed circles for candidates, and dashed lines between matched centers. When judging large-radius mismatches, trust the TSV arc residual columns more than the center-link length.

### 12. Correct the helper-circle sequence from matches

After reviewing the match output, generate a corrected Course CAD-readable helper-circle JSON.

Use the original line-arc fitting CAD JSON as the ordered editable base, and use the arc-residual match JSON as the replacement source:

```bash
uv run --project course_image_parser python course_image_parser/correct_helper_circles_from_matches.py \
  tmp/<name>/line_arc_path_fitting/<name>/course_cad_model.json \
  tmp/<name>/helper_circle_matching/consolidated_arc_residual/helper_circle_matches.json \
  --out-dir tmp/<name>/helper_circle_correction \
  --name consolidated_corrected \
  --trace-report tmp/<name>/centerline_trace/<name>/report.json \
  --image-path tmp/<name>/support_circle_detection/<name>/magenta_overlay.png \
  --min-match-score 0.4
```

Expected correction behavior:

- for each matched fitted arc, replace helper-circle radius and center with the matched consolidated design-candidate result, including approximate values
- preserve candidate turn direction when present
- merge consecutive fitted arcs that match the same consolidated design-candidate helper circle
- keep unmatched fitted entries as line-trace-derived fallbacks
- write a Course CAD-readable corrected JSON, a detailed correction report, a TSV, and an overlay image

Touch correction is deliberately conservative in this step:

- only move helper circles whose own `approx_center` is true
- if the approx-center circle touches both neighboring circles, apply Fit Touch only when both neighboring circles have confirmed dimensions (`approx_radius=false` and `approx_center=false`)
- if it touches only one neighboring circle, apply Fit Prev or Fit Next only when that neighboring circle has confirmed dimensions
- if the first or last helper circle is approximate, fit it to the confirmed neighboring circle and the confirmed `START`-`GOAL` line when possible
- do not use an approximate-radius or approximate-center neighbor as a Fit Touch anchor
- store fitted centers with high enough precision for Course CAD tangent detection; tiny positive slack is intentional

Expected outputs:

- `tmp/<name>/helper_circle_correction/consolidated_corrected/corrected_course_cad_model.json`
- `tmp/<name>/helper_circle_correction/consolidated_corrected/helper_circle_corrections.json`
- `tmp/<name>/helper_circle_correction/consolidated_corrected/corrected_helper_circles.tsv`
- `tmp/<name>/helper_circle_correction/consolidated_corrected/corrected_helper_circles.png`

Validate the corrected CAD JSON:

```bash
PYTHONPATH=src python - <<'PY'
from robotrace_course_cad.io.json_io import load_course_model
from robotrace_course_cad.solver.course_solver import solve_course

model = load_course_model("tmp/<name>/helper_circle_correction/consolidated_corrected/corrected_course_cad_model.json")
solution = solve_course(model)
print(len(model.circles), "helper circles")
for issue in solution.issues:
    print(issue.severity, issue.message)
PY
```

Treat remaining solver issues as review targets, not automatic failure. The corrected JSON is still a candidate until the user reviews geometry, unresolved approximate centers, and any remaining tangent/arc/intersection issues.

Even when this corrected JSON is geometrically imperfect, provide `corrected_course_cad_model.json` and its issue summary to the user. Do not substitute the intermediate line-trace `course_cad_model.json`, a no-touch-adjust line-trace JSON, or any other line-trace-only JSON as the result. The line-trace JSON may be mentioned only as an intermediate base/debug artifact, never as an alternative final output for this workflow.

### 13. Produce a user-facing intermediate report

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
- any OCR ambiguity in red radius/coordinate text
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
- intermediate line-arc fitting `course_cad_model.json` used as debug/base only
- Course CAD solver issue summary
- support-circle candidate overlay, TSV, and JSON
- slalom candidate overlay, TSV, and JSON
- red-text OCR JSON
- consolidated design-candidate JSON with approximation flags
- arc-residual helper-circle matching report, TSV, and visualization
- corrected Course CAD-readable helper-circle JSON, correction TSV, and overlay
- Course CAD solver issue summary for the corrected JSON

### 14. Mandatory pause

Stop after reporting the fitted line/arc, support-circle/slalom candidates, red-text OCR, consolidated design candidates, arc-residual matching, and corrected helper-circle CAD JSON findings.

Ask the user whether to:

1. accept one board interpretation and one start/goal candidate
2. accept the current centerline point sequence or review its failure points
3. review ambiguous candidates together
4. review or manually repair the corrected helper-circle CAD JSON
5. review the consolidated design-candidate list and approximation flags

Do not continue automatically past this checkpoint.

## Validation Checklist

Before stopping, make sure all of the following are true:

- board contour was checked by both script output and visual inspection
- board size was justified by either explicit image evidence or a clearly stated inference
- start/goal candidates were generated from the scripted detector
- later AI image recognition was used only for red-text OCR, not support/slalom candidate accept/reject, geometry merging, or final helper-circle selection
- any visible red text or coordinate labels were captured as OCR hypotheses in `line_design_info.json`
- the centerline mask excluded colored overlay lines before morphology
- the tracer used the confirmed `GOAL -> START` departure direction at `START`
- the traced TSV includes the confirmed `START` and `GOAL` as first and last points after endpoint insertion
- the centerline trace outcome was reviewed in overlay form, not only by numeric report
- arc radii in `line_arc_segments.json` are `R10 cm` or larger and multiples of `5 cm` unless `--no-quantize-arc-radius` was used
- start-touching and goal-touching candidate segments were constrained to the confirmed `START`-`GOAL` line
- `line_arc_segments.json` was used as the fitted input for helper-circle matching, not the interval-free `course_cad_model.json`
- intermediate `course_cad_model.json` loads with `load_course_model` when generated, but is not treated as final geometry truth
- support-circle candidates were generated when red/magenta helper-circle annotations are present or suspected
- `magenta_overlay.png` was inspected to confirm that red support-circle annotations were actually extracted
- R50/60 slalom candidates were generated when slalom templates are present or suspected
- slalom candidate filtering was handled by `detect_slalom_template.py` and `consolidate_design_candidates.py`, not by AI judgment
- red text near top support-circle and slalom areas was OCR'd for radius, center, and endpoint coordinates
- visible printed slalom endpoint coordinates were read as text hypotheses; detector-derived fractional template coordinates were not treated as text reads
- `consolidate_design_candidates.py` was run after OCR and scripted detection outputs were available
- consolidated ordinary helper circles and nested slalom helper circles include `radius_cm`, `center_cm`, `approx_radius`, and `approx_center`
- exact red text reads and approximate geometry/template inferences were not mixed without setting the corresponding approximation flag
- arc-residual matching was generated from `line_arc_segments.json` and the consolidated design-candidate list
- match TSV was reviewed for `arc_rms_error_cm`, especially for large-radius or radius-mismatched arcs
- corrected helper-circle CAD JSON was generated from the match results
- correction-stage Fit Touch/Fit Prev/Fit Next moved only `approx_center` circles and only used confirmed-dimension neighbors as anchors
- corrected CAD JSON loads with `load_course_model`
- Course CAD solver issues for the corrected JSON were summarized, especially `No tangent candidate`, short tangent, short arc, and intersection messages
- corrected CAD JSON was provided to the user for judgment even if those solver issues remain
- intermediate line-trace `course_cad_model.json`, no-touch-adjust JSON, or any line-trace-only JSON was not presented as a replacement final output
- unresolved conflicts were reported to the user
- the workflow stopped before manual helper-circle repair, course-order finalization, or final JSON approval

## Notes

- Prefer the dedicated `course_image_parser` environment over the CAD runtime environment for image-analysis work.
- If multiple batch results exist, compare them consistently per image rather than mixing outputs from different runs.
- If a prior `*_notes.md` file exists and the user provides corrections, update that notes file before moving to any later stage.
- The scripted workflow ends after line/arc fitting, support-circle/slalom candidate detection, red-text OCR, scripted design-candidate consolidation, arc-residual matching, and corrected helper-circle CAD JSON generation. Continue to manual geometry repair, course-order finalization, or final JSON approval only after user review.
- Never substitute line-trace-only CAD JSON for the consolidated-and-corrected output. If the corrected output has tangent or solver issues, provide that output plus the issue summary and ask the user how to proceed.
