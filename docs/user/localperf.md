# LocalPerf benchmarks

Open **Settings → Hardware optimization → Benchmarks** to compare a model across compatible execution backends. Select Quick for three repetitions or Thorough for seven. Both use the fixed 12-prompt `LocalPerf-Core-v1` workload and run one unmeasured warmup before collection.

Open **Settings → Hardware optimization → Leaderboard** to compare saved runs. Choose a model, suite, backend, and KPI to rank conforming results, compare throughput against time to first token, and inspect the selected backend's history and per-prompt evidence. Detected but untested options remain visible as **Not tested** and can be handed back to the benchmark runner; they are never assigned a verified rank until a conforming run completes. Compare only runs with the same workload version and hash when judging a backend or software change.

JSON_CODR records generation tokens per second, streaming time to first token, peak VRAM, duration, token counts, success, and bounded quality results for the coding, JSON, and SQL prompts. A configuration is conforming only when every expected sample and quality check executes successfully. Missing required measurements and partial runs are reported as non-conforming and are not eligible for automatic selection.

Each configuration is stored under the JSON_CODR data directory at `localperf/runs/<evaluation-id>/aggregate.json` and `samples.jsonl`. The configuration hash includes model, backend, profile, hardware, and software identity so results from changed environments are not silently combined. The **Clear benchmark data** button removes benchmark history; it does not remove models, provider environments, settings, or chat sessions.

V1.0.10 implements the LocalPerf workload, artifacts, bounded quality validation, deterministic paired comparison primitives, and UI reporting. External telemetry collectors, hosted dashboards, and notifications are outside this release.

JSON_CODR can export a selected run as a `.localperf.zip` package containing the standard workload, schema, method, report template, aggregate, and samples. Exports remove system-identifying hardware and software fields unless **Include full system details** is explicitly selected. Imports are previewed and validated before persistence; packages containing details require separate consent to retain them. Imported results are reference evidence and cannot automatically become a local baseline.
