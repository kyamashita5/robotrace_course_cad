---
name: robotrace-course-cad-review
description: Use when reviewing code, diffs, branches, pull requests, or the full repository for Robotrace Course CAD; checks geometry correctness, model-solver-render boundaries, JSON compatibility, PySide6 behavior, exports, and tests.
---

# Robotrace Course CAD Review

Use this skill only in the `robotrace_course_cad` repository when the user asks for a code review, regression analysis, pull request review, branch review, or repository-wide quality audit.

The review is evidence-driven and read-only unless the user separately asks for fixes. Findings are the primary output. Do not spend the response summarizing code that has no actionable problem.

## Sources Of Truth

Read these before judging intentional behavior:

- `AGENTS.md` for repository conventions and validation commands
- `doc/robotrace_course_cad_spec.md` for domain rules, units, coordinates, and architecture
- `README.md` for supported user-visible behavior
- relevant tests and synthetic references for established behavior

Treat implementation and tests as evidence, not automatically as the specification. Call out conflicts between docs, tests, and code rather than silently choosing one.

## 1. Establish The Review Scope

Determine whether the request targets:

- uncommitted work: inspect both staged and unstaged changes
- a commit or branch: inspect the complete diff from the stated or inferred base
- a pull request: inspect every included commit and the aggregate diff
- the full repository: inspect all production modules, tests, entry points, and persisted formats

Useful commands include:

```bash
git status --short
git diff --stat
git diff
git diff --cached
git log --oneline -10
```

Do not review only the newest commit when earlier commits are in scope. Do not treat unrelated dirty-worktree changes as part of the target unless they are in the requested scope.

Map each changed behavior through its callers and consumers. A solver change, for example, may affect validation, rendering, export, synthetic references, and UI messages even if only one module changed.

## 2. Prioritize Correctness Risks

Search for concrete behavioral failures, regressions, unsafe assumptions, and missing tests. Do not report formatting preferences or speculative refactors unless they create a real maintenance or correctness risk.

Use these severities:

- `Critical`: data loss, unusable application, broadly corrupt output, or a severe safety/security issue
- `High`: likely wrong course geometry, persisted-data breakage, crash in a supported workflow, or major user-visible regression
- `Medium`: incorrect edge-case behavior, misleading validation/export, state-sync defect, or meaningful missing coverage
- `Low`: limited robustness or maintainability issue with a concrete future failure mode

Only report a finding when all of these are available:

- the exact file and line or smallest useful line range
- the input, state, or sequence that triggers it
- the observed or logically demonstrated impact
- why existing guards or tests do not prevent it

Before finalizing a finding, trace the relevant call path and actively look for code that disproves it.

## 3. Repository-Specific Review Checklist

### Architecture And State Ownership

- Keep editable source state in `CourseModel`, derived geometry in `CourseSolution`, and presentation in `render/` and `ui/`.
- Geometry and course-rule decisions belong in `solver/`, not Qt widgets or scene items.
- JSON persistence belongs in `io/json_io.py`; rendering/export must consume the derived solution rather than independently solving geometry.
- `QGraphicsItem` objects must not become authoritative design state.
- Check that model edits trigger one coherent solve and refresh, without stale solution, table, selection, scene, or issue state.

### Geometry And Numerical Correctness

- Design/model units are centimeters. Check every conversion at solver, renderer, export, and page-unit boundaries.
- Internal coordinates are mathematical coordinates: positive `x` right and positive `y` up. Negate `y` only at the Qt screen-coordinate boundary.
- Verify CW/CCW orientation, left/right normals, signed angles, Qt arc sweep conventions, and start/goal travel direction.
- Preserve the closed-loop connection convention, including the final `C[n-1] -> C[0]` start/goal tangent and index alignment among circles, tangents, arcs, markers, and issue highlights.
- Check tangent-to-arc endpoint continuity, arc length/angle consistency, line width, bounds, margins, intersections, marker sides, and start/goal placement.
- Exercise degenerate and near-degenerate inputs: too few circles, coincident centers, nested/touching circles, equal radii, zero-length vectors, missing tangents/arcs, very short segments, boundary contact, and floating-point threshold crossings.
- Reject accidental `NaN`, infinity, division by zero, unstable candidate selection, exact-float comparisons where a tolerance is required, and tolerances that are inconsistent across modules.
- Ensure deterministic tie-breaking. The same model must not produce geometry that depends on incidental collection order or platform behavior.

### Validation And Partial Solutions

- Geometry problems should normally appear in `CourseSolution.issues`, with accurate severity and related IDs/highlights, rather than being hidden in UI-only text.
- Verify that downstream validation tolerates `None` tangents/arcs and incomplete solutions without crashing or reporting misleading secondary errors.
- Check that early returns preserve expected list lengths and index meaning.
- Ensure `error`, `warning`, and `info` are not confused and that messages describe the actual violated rule.
- Verify course constraints against the spec, especially line width, edge margin, orthogonal crossings, straight clearance around crossings, and start/goal length.

### Model And JSON Persistence

- Check save/load round trips for every model field, enum, default, optional value, and numeric conversion.
- Treat shipped example JSON and user-created course files as persisted data. Flag schema or default changes that silently alter existing files.
- Distinguish intentional legacy-key support from accidental schema drift.
- Look for surprising mutation during serialization, especially circle ID renumbering and shared mutable lists.
- Invalid or incomplete JSON should fail clearly rather than creating a plausible but incorrect course.

### Qt UI And Rendering

- Reuse `QApplication.instance()` in tests and use headless Qt for automation.
- Check signal recursion guards, lambda row capture, selection preservation, drag/table synchronization, locked-circle behavior, file-dialog cancellation, and save/export error paths.
- Rendering must only convert coordinates at the Qt boundary and must render partial solutions safely.
- Verify z-order, scene bounds, pens measured in the intended units, readable text orientation, and consistency between on-screen and final drawing output.
- Ensure `QPainter` and other Qt resources are finalized on exceptions.
- Keep the light Fusion theme behavior compatible with new widgets and palettes.

### Export And Material Estimates

- SVG/PDF output must use the same `CourseSolution` geometry as the UI.
- Check page orientation, fit calculations, margins, clipping, empty-scene behavior, marker/helper-circle options, and all geometry included in exported bounds.
- Verify that occupied grid cells and material estimates account for arcs, tangents, markers, line width, and boundary cases consistently.
- Treat changes to printed dimensions, labels, or coordinate annotations as user-visible correctness changes, not cosmetic changes.

### Tests And Regression Protection

- Match tests to the owning layer: geometry in solver tests, persistence in JSON tests, rendering/export in Qt tests, orchestration in UI tests.
- Require focused tests for bug-triggering inputs and boundary values, not only happy-path examples.
- Use numerical assertions with a domain-appropriate tolerance and verify orientation/endpoints as well as lengths.
- Synthetic references are regression fixtures. Do not accept regenerating them merely to make a changed solver pass; first establish that the new geometry is intended and correct.
- Check both expected issues and absence of unexpected errors. A test that only asserts object counts may miss wrong geometry.

## 4. Validate Findings

Run the narrowest relevant test module first, then the full suite when feasible:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest tests.test_<module>
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

For a suspected bug not covered by tests, prefer a minimal read-only reproduction using existing public functions. Do not modify production files during a review. If dependencies or the Qt runtime prevent execution, continue static analysis and report the validation gap explicitly.

Use the test result as evidence, not as proof that no defect exists. Passing tests do not dismiss an uncovered input or invariant violation.

## 5. Report Format

List findings first, ordered by severity and then by impact. Use this form:

```markdown
- **High** `src/robotrace_course_cad/solver/example.py:42`: Short finding title
  Trigger and impact in one compact paragraph, including why current tests or guards miss it.
```

Keep bullets flat; put supporting text in the same bullet or separate paragraphs.

After findings, include only the sections that add value:

- `Open Questions`: ambiguities that affect whether behavior is correct
- `Validation`: commands run and their result, including failures or skipped checks
- `Summary`: one or two sentences on reviewed scope and residual risk

If no findings are discovered, say so explicitly and state the remaining testing or scope limitations. Do not invent findings to fill the report.

## Review Completion Checklist

Before responding, confirm that:

- the complete requested diff or repository scope was inspected
- changed public behavior was traced through callers and consumers
- applicable geometry, persistence, UI, render, and export invariants were checked
- relevant tests were read and, where feasible, executed
- every finding is reproducible or logically demonstrated and line-referenced
- findings are not duplicates, style-only comments, or already prevented elsewhere
