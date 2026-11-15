(function attachBenchmarkLeaderboard(root) {
  "use strict";

  const numberOrNull = (value) => value === null || value === undefined || value === ""
    ? null
    : (Number.isFinite(Number(value)) ? Number(value) : null);

  function percentile(sorted, ratio) {
    if (!sorted.length) return null;
    const position = (sorted.length - 1) * ratio;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    const value = sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
    return Number(value.toFixed(3));
  }

  function percentiles(values) {
    const sorted = (Array.isArray(values) ? values : [])
      .map(numberOrNull).filter((value) => value !== null).sort((a, b) => a - b);
    if (!sorted.length) return { min: null, p50: null, p90: null, max: null };
    return { min: sorted[0], p50: percentile(sorted, .5), p90: percentile(sorted, .9), max: sorted.at(-1) };
  }

  function resultRow(session, result) {
    const tests = Array.isArray(result.tests) ? result.tests.map((test) => ({ ...test })) : [];
    const throughput = numberOrNull(result.tokens_per_second);
    const ttft = percentiles(tests.map((test) => test.ttft_ms)).p50;
    const peakVram = percentiles(tests.map((test) => test.peak_vram_mb)).max;
    const total = numberOrNull(result.average_total_seconds) ?? percentiles(tests.map((test) => test.total_seconds)).p50;
    const speedup = numberOrNull(result.speedup_vs_cpu);
    const conforming = result.localperf?.conformance?.conforming !== false;
    const status = result.status || "unavailable";
    return {
      id: `${session.id || "legacy"}:${result.backend || result.runtime || "unknown"}`,
      session_id: session.id || "legacy",
      created_at: session.created_at || "",
      model: session.model || "Unknown model",
      suite: session.suite || "Unknown suite",
      workload_version: session.workload_version || "Unknown workload",
      workload_hash: session.workload_hash || "",
      backend: result.backend || result.runtime || "unknown",
      name: result.name || result.backend || result.runtime || "Unknown backend",
      status,
      tested: result.tested ?? status !== "not_tested",
      probe_verified: result.verified === true,
      runnable: result.runnable !== false,
      compatible: result.compatible !== false,
      availability_reason: result.availability_reason || result.reason || null,
      conforming,
      eligible_rank: status === "completed" && conforming,
      tokens_per_second: throughput,
      ttft_ms: ttft,
      average_total_seconds: total,
      peak_vram_mb: peakVram,
      speedup_vs_cpu: speedup,
      performance_index: speedup === null ? null : Number((speedup * 100).toFixed(1)),
      gpu_percent: numberOrNull(result.gpu_percent),
      evaluation_id: result.localperf?.evaluation_id || null,
      localperf: result.localperf ? { ...result.localperf } : null,
      error: result.error || null,
      rejection_reasons: Array.isArray(result.rejection_reasons) ? [...result.rejection_reasons] : [],
      conformance_reasons: Array.isArray(result.localperf?.conformance?.reasons) ? [...result.localperf.conformance.reasons] : [],
      runtime_metadata: result.runtime_metadata || result.localperf?.runtime_metadata || null,
      tests,
    };
  }

  function buildRows(history, candidates, sessionId) {
    const sessions = Array.isArray(history) ? history : [];
    const session = sessions.find((item) => item?.id === sessionId) || sessions[0];
    if (!session) return [];
    const rows = (Array.isArray(session.results) ? session.results : []).map((result) => resultRow(session, result || {}));
    const seen = new Set(rows.map((row) => row.backend));
    for (const candidate of Array.isArray(candidates) ? candidates : []) {
      if (!candidate?.id || seen.has(candidate.id)) continue;
      rows.push(resultRow(session, {
        backend: candidate.id,
        name: candidate.name || candidate.id,
        status: candidate.runnable === false || candidate.compatible === false ? "unavailable" : "not_tested",
        verified: candidate.verified,
        runnable: candidate.runnable,
        compatible: candidate.compatible,
        availability_reason: candidate.reason || candidate.error || null,
        tested: false,
        tests: [],
      }));
      seen.add(candidate.id);
    }
    return rows;
  }

  function filterAndRank(rows, filters = {}) {
    const metric = filters.metric || "tokens_per_second";
    const lowerIsBetter = new Set(["ttft_ms", "average_total_seconds", "peak_vram_mb"]);
    const search = String(filters.search || "").trim().toLowerCase();
    const filtered = (Array.isArray(rows) ? rows : []).filter((row) => {
      if (filters.model && filters.model !== "all" && row.model !== filters.model) return false;
      if (filters.backend && filters.backend !== "all" && row.backend !== filters.backend) return false;
      if (filters.suite && filters.suite !== "all" && row.suite !== filters.suite) return false;
      return !search || `${row.model} ${row.backend} ${row.name}`.toLowerCase().includes(search);
    });
    const ordered = filtered.map((row, index) => ({ row: { ...row }, index })).sort((left, right) => {
      if (left.row.eligible_rank !== right.row.eligible_rank) return left.row.eligible_rank ? -1 : 1;
      const a = numberOrNull(left.row[metric]);
      const b = numberOrNull(right.row[metric]);
      if (a === null && b !== null) return 1;
      if (a !== null && b === null) return -1;
      if (a !== null && b !== null && a !== b) return lowerIsBetter.has(metric) ? a - b : b - a;
      return left.index - right.index;
    });
    let rank = 0;
    return ordered.map(({ row }) => {
      const metricEligible = row.eligible_rank && numberOrNull(row[metric]) !== null;
      return { ...row, rank: metricEligible ? ++rank : null };
    });
  }

  function buildTrend(history, row, metric = "tokens_per_second") {
    if (!row) return [];
    const points = [];
    for (const session of Array.isArray(history) ? history : []) {
      if (session?.model !== row.model || session?.suite !== row.suite) continue;
      if ((session.workload_version || "Unknown workload") !== row.workload_version) continue;
      if ((session.workload_hash || "") !== row.workload_hash) continue;
      const result = (Array.isArray(session.results) ? session.results : []).find(
        (item) => (item.backend || item.runtime) === row.backend
      );
      if (!result) {
        points.push({ session_id: session.id || "legacy", created_at: session.created_at || "", value: null, eligible: false });
        continue;
      }
      const normalized = resultRow(session, result);
      const eligible = normalized.eligible_rank && numberOrNull(normalized[metric]) !== null;
      points.push({
        session_id: session.id || "legacy",
        created_at: session.created_at || "",
        value: eligible ? numberOrNull(normalized[metric]) : null,
        eligible,
      });
    }
    return points.sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  }

  function scalePoints(points, bounds = {}) {
    if (!Array.isArray(points) || !points.length) return [];
    const width = Number(bounds.width) || 400;
    const height = Number(bounds.height) || 200;
    const padding = Number(bounds.padding) || 20;
    const xs = points.map((point) => Number(point.x)).filter(Number.isFinite);
    const ys = points.map((point) => Number(point.y)).filter(Number.isFinite);
    if (!xs.length || !ys.length) return [];
    const xMin = Math.min(...xs); const xMax = Math.max(...xs);
    const yMin = Math.min(...ys); const yMax = Math.max(...ys);
    const xSpan = xMax - xMin; const ySpan = yMax - yMin;
    return points.map((point) => ({
      ...point,
      cx: xSpan ? padding + ((Number(point.x) - xMin) / xSpan) * (width - 2 * padding) : width / 2,
      cy: ySpan ? height - padding - ((Number(point.y) - yMin) / ySpan) * (height - 2 * padding) : height / 2,
    }));
  }

  function selectRow(rows, selectedId) {
    if (!Array.isArray(rows) || !rows.length) return null;
    return rows.find((row) => row.id === selectedId) || rows[0];
  }

  function chooseSession(history, selectedId, model = "all", suite = "all") {
    const sessions = Array.isArray(history) ? history : [];
    const matches = (session) => (model === "all" || session.model === model) && (suite === "all" || session.suite === suite);
    const current = sessions.find((session) => session.id === selectedId);
    return current && matches(current) ? current : sessions.find(matches) || null;
  }

  root.JSONCodrLeaderboard = { buildRows, filterAndRank, percentiles, buildTrend, scalePoints, selectRow, chooseSession };
})(typeof window === "undefined" ? globalThis : window);
