# Benchmark Leaderboard Design

## Intent

Add a dedicated **Leaderboard** subpage beneath Hardware → Performance Benchmarks so users can compare benchmark evidence visually in the style of Hugging Face leaderboards. The page should make model, backend, and system changes easy to rank and inspect without conflating performance with model quality.

## Goals

- Present saved LocalPerf benchmark runs as a searchable, sortable performance leaderboard.
- Show headline KPIs for throughput, time to first token (TTFT), total duration, peak VRAM, CPU-relative speed, and verification success.
- Compare a selected CPU, GPU, or accelerator result against every detected option with compatible benchmark evidence so users can see the measured benefit of each available optimization.
- Provide two compact visual comparisons: throughput versus TTFT and performance history over time.
- Let users expand a leaderboard row into detailed per-prompt samples, percentile statistics, runtime metadata, conformance, failures, and verification notes.
- Reuse the existing benchmark history API and its bounded 20-run persistence.
- Preserve benchmark execution as its own subpage; the leaderboard reads results and does not change the active backend.

## Non-goals

- Do not claim model quality, coding correctness, or Hugging Face evaluation scores; this is a local performance leaderboard only.
- Do not submit data to Hugging Face or any remote service.
- Do not add a third-party charting library.
- Do not change the LocalPerf workload, benchmark execution, backend selection, or history retention in this feature.
- Do not compare incompatible samples silently. Runs with different suites or workload versions remain visible but are labeled and excluded from direct normalized ranking unless the user explicitly filters them together.

## Constraints

- The application remains localhost-only and must work offline.
- Existing benchmark records and legacy-normalized history must render without migration.
- Charts must support light and dark themes, keyboard navigation, and non-visual equivalents.
- Tables and charts must remain responsive in the resizable global navigation layout.
- Rendering must stay lightweight for the current maximum of 20 saved runs.

## Chosen approach

The user selected a Hugging Face–style leaderboard rather than a chart-first dashboard. The chosen design is a leaderboard-first report with supporting KPI cards and compact charts:

1. **Leaderboard header** — title, result count, comparison controls, and LocalPerf export access.
2. **KPI cards** — best throughput, lowest TTFT, lowest measured peak VRAM, and verified-run rate for the active compatible cohort.
3. **Filter and sort toolbar** — search, model, backend, suite/workload, and metric selectors.
4. **Ranked table** — rank, model/backend, performance index, tokens/s, TTFT, total duration, peak VRAM, CPU-relative speed, date, and status.
5. **Comparison visuals** — an SVG scatter plot for throughput versus TTFT and an SVG trend line for the selected model/backend across time.
6. **Evidence drawer** — expandable p50/p90/min/max values, samples, runtime metadata, LocalPerf conformance, failures, and verification notes.

The other approaches considered were a table-only leaderboard, which would not satisfy the visual-comparison goal, and a chart-first dashboard, which would make exact rankings and detailed evidence harder to inspect.

## Navigation and information architecture

- Rename the existing benchmark navigation label to **Performance benchmarks**.
- Keep the current benchmark runner and immediate result list under that subpage.
- Add a sibling **Leaderboard** hardware subsection directly below Performance benchmarks.
- Keep **Results & history** as the evidence/history management page for selecting raw runs, clearing history, and LocalPerf packaging. The Leaderboard is a read-only analytical view over the same data.
- Selecting Leaderboard loads history on demand and preserves the current filters while navigating elsewhere during the session.

## Ranking and comparability

- One leaderboard row represents one backend result within a benchmark session, not the whole session. Its stable identity combines the benchmark ID and concrete backend ID.
- Default cohort: every backend result from the newest selected benchmark session. A session already fixes the model, suite, workload, software build, and machine, so this is the authoritative apples-to-apples comparison.
- Selecting any result, including a GPU result, builds a comparison cohort across the machine's currently detected concrete candidates—CPU, Ollama GPU, CUDA variants, Vulkan, NPU devices, OpenVINO, DirectML, WinML, Ryzen AI, and future detected backends—for that session's model, suite, and workload version.
- A detected backend without matching evidence remains in the comparison set as **Not tested** with an action that returns the user to Performance benchmarks with that backend preselected. It is never assigned a zero score.
- Results from older sessions do not fill a missing direct-comparison slot because hardware or software configuration may have changed. They appear only in the explicitly labeled historical trend for the same model, suite, workload version, and concrete backend ID.
- Default ranking metric: generation tokens per second, descending.
- Users may rank by TTFT, total duration, peak VRAM, or CPU-relative speed.
- A displayed **Performance Index** is relative rather than universal: CPU baseline equals 100 for the same model, suite, workload version, and run. Candidate index is `100 × speedup_vs_cpu`. If a comparable CPU baseline is unavailable, the index displays “—”.
- Peak VRAM is not folded into the index because CPU’s zero GPU memory would distort the score. It remains a sortable KPI.
- Failed, incomplete, nonconforming, or unverified rows remain visible with status labels but do not receive a verified rank.
- **Ranked** means the backend result completed successfully and its LocalPerf evaluation conforms. Backend probe verification remains a separate badge because it describes runtime readiness rather than benchmark validity.
- Different models may be compared on performance metrics, but the UI explicitly states that faster output does not imply better answer quality.

## Statistics and visual behavior

- Aggregate p50 and p90 values client-side from the existing per-prompt samples for throughput, TTFT, total duration, and peak VRAM.
- Scatter plot: x-axis TTFT (lower is better), y-axis tokens/s (higher is better), one accessible point per eligible result.
- Backend comparison bars show every detected option side by side for the selected metric, including labeled Not tested slots, so GPU gains and compatibility fallbacks remain visible together.
- Trend plot: selected model/backend and metric over benchmark creation time. Missing or incompatible points create gaps rather than zeroes.
- Every chart includes axis labels, a legend, tooltips/focus labels, and an adjacent screen-reader summary/table.
- With fewer than two comparable points, show the available value and explain why a comparison graph is unavailable.

## Data flow

- Continue using `GET /api/hardware/benchmarks`; no new endpoint or database is required. The existing response already contains session metadata, backend aggregates, per-prompt tests, LocalPerf conformance, and status. Details unavailable in legacy records remain explicitly unavailable rather than being reconstructed.
- Combine benchmark history with the existing hardware-detection response to obtain the current concrete backend inventory.
- Normalize leaderboard rows in the web client from benchmark-level metadata, result aggregates, and per-prompt tests. A row retains its LocalPerf evaluation ID so exporting a selected row exports that exact evaluation.
- Keep derived filters, percentiles, ranks, and SVG coordinates in small pure JavaScript helpers so they can be unit/static tested.
- Re-render from the cached history when a filter or sort changes; refetch after a benchmark finishes or history is cleared.
- The most recently chosen Results & history session becomes the Leaderboard cohort for the current browser session; otherwise the newest saved session is selected.
- A Not tested action navigates to Performance benchmarks and preselects the session's model and suite plus the exact currently detected backend ID. If that candidate is no longer detected, the action is disabled with an explanation.

## Error and empty states

- No history: explain that a benchmark must be run first and link back to Performance benchmarks.
- No comparable cohort: retain filters and explain which suite/workload constraint excluded rows.
- Missing backend evidence: show the detected backend as Not tested and offer a route back to the benchmark runner; do not imply that unavailable evidence means poor performance.
- Partial legacy records: show available fields and “Unavailable” for missing metrics.
- Failed backend: show the error in row details without plotting or ranking it.

## Testing and acceptance

- Static UI tests cover the new Leaderboard subsection, controls, table, chart containers, accessible labels, and asset hooks.
- JavaScript behavior tests or pure-helper tests cover compatible cohort filtering, ranking, percentile calculation, missing data, and stable sorting.
- Existing benchmark API, LocalPerf, navigation, and full regression suites must remain green.
- Integrated browser verification confirms navigation, filtering, sorting, row expansion, both graphs, light/dark rendering, and empty-state behavior.
- Acceptance requires that the page clearly identifies itself as performance-only and never labels unlike workload results as directly comparable.
