import { useCallback, useEffect, useRef, useState } from "react";
import { fetchProject, fetchProjectTags } from "../projectsApi";
import { fetchProjectRuns, type CustomMetricColumn, type MetricFilter, type Run } from "../runsApi";
import { subscribe } from "../serverEvents";
import { buildMetricFilterPayload, toUtcFilterTimestamp, type Filters } from "../projectFilters";
import type { Tag } from "../tags";

type QuerySort = { key: string; direction: "asc" | "desc" } | null;

export function useProjectRunsData({
  completedPage,
  completedRowsPerPage,
  completedSort,
  filters,
  projectId,
}: {
  completedPage: number;
  completedRowsPerPage: number;
  completedSort: QuerySort;
  filters: Filters;
  projectId?: string;
}) {
  const [projectName, setProjectName] = useState("");
  const [runningRuns, setRunningRuns] = useState<Run[]>([]);
  const [completedRuns, setCompletedRuns] = useState<Run[]>([]);
  const [completedTotal, setCompletedTotal] = useState(0);
  const [distinctVersions, setDistinctVersions] = useState<string[]>([]);
  const [customMetricColumns, setCustomMetricColumns] = useState<CustomMetricColumn[]>([]);
  const [projectTags, setProjectTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [completedRefreshKey, setCompletedRefreshKey] = useState(0);
  const prevTextRef = useRef({ name: "", runId: "" });

  const loadProjectName = useCallback(() => {
    if (!projectId) return;
    fetchProject(projectId).then((project) => setProjectName(project.name)).catch(console.error);
  }, [projectId]);

  useEffect(loadProjectName, [loadProjectName]);

  useEffect(() => {
    return subscribe("project_list_changed", loadProjectName);
  }, [loadProjectName]);

  useEffect(() => {
    if (!projectId) return;
    return subscribe("run_list", (message) => {
      const running = message.runs.filter((run) => run.status === "running" && run.project_id === projectId);
      setRunningRuns(running);
      setCompletedRefreshKey((value) => value + 1);
    });
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    return subscribe("graph_update", (message) => {
      if (!message.run_id || !Object.prototype.hasOwnProperty.call(message, "active_runtime_seconds")) return;
      const activeRuntimeSeconds = message.active_runtime_seconds ?? null;
      setRunningRuns((previous) => previous.map((run) => (
        run.run_id === message.run_id
          ? { ...run, active_runtime_seconds: activeRuntimeSeconds }
          : run
      )));
    });
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;

    const previous = prevTextRef.current;
    const textChanged = previous.name !== filters.name.value || previous.runId !== filters.runId;
    prevTextRef.current = { name: filters.name.value, runId: filters.runId };

    const controller = new AbortController();
    const delay = textChanged ? 300 : 0;

    const params: {
      limit: number;
      offset: number;
      sort?: string;
      dir?: string;
      name?: string;
      run_id?: string;
      label?: string[];
      tag_id?: string[];
      version?: string[];
      metric_filters?: Record<string, MetricFilter>;
      time_from?: string;
      time_to?: string;
      latency_min?: number;
      latency_max?: number;
    } = {
      limit: completedRowsPerPage,
      offset: (completedPage - 1) * completedRowsPerPage,
    };
    if (completedSort) {
      params.sort = completedSort.key;
      params.dir = completedSort.direction;
    }
    if (filters.name.value) params.name = filters.name.value;
    if (filters.runId) params.run_id = filters.runId;
    if (filters.label.size > 0) params.label = Array.from(filters.label);
    if (filters.tags.size > 0) params.tag_id = Array.from(filters.tags);
    if (filters.version.size > 0) params.version = Array.from(filters.version);
    const metricFilters = buildMetricFilterPayload(filters.customMetrics);
    if (Object.keys(metricFilters).length > 0) params.metric_filters = metricFilters;
    if (filters.startTime.from) params.time_from = toUtcFilterTimestamp(filters.startTime.from, false);
    if (filters.startTime.to) params.time_to = toUtcFilterTimestamp(filters.startTime.to, true);
    if (filters.latency.enabled) {
      params.latency_min = filters.latency.min;
      params.latency_max = filters.latency.max;
    }

    const timer = window.setTimeout(async () => {
      try {
        const [response, tags] = await Promise.all([
          fetchProjectRuns(projectId, params, controller.signal),
          fetchProjectTags(projectId),
        ]);
        setRunningRuns(response.running);
        setCompletedRuns(response.finished);
        setCompletedTotal(response.finished_total);
        setDistinctVersions(response.distinct_versions);
        setCustomMetricColumns(response.custom_metric_columns);
        setProjectTags(tags);
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        console.error("Failed to fetch runs:", error);
      } finally {
        setLoading(false);
      }
    }, delay);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [projectId, completedPage, completedRowsPerPage, completedSort, filters, completedRefreshKey]);

  return {
    completedRuns,
    completedTotal,
    customMetricColumns,
    distinctVersions,
    loading,
    projectName,
    projectTags,
    runningRuns,
  };
}
