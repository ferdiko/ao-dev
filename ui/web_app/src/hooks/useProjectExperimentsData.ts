import { useCallback, useEffect, useRef, useState } from "react";
import { fetchProject, fetchProjectExperiments, fetchProjectTags } from "../api";
import type { CustomMetricColumn, Experiment, MetricFilter } from "../api";
import { subscribe } from "../serverEvents";
import { buildMetricFilterPayload, toUtcFilterTimestamp, type Filters } from "../projectFilters";
import type { Tag } from "../tags";

type QuerySort = { key: string; direction: "asc" | "desc" } | null;

export function useProjectExperimentsData({
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
  const [runningExperiments, setRunningExperiments] = useState<Experiment[]>([]);
  const [completedExperiments, setCompletedExperiments] = useState<Experiment[]>([]);
  const [completedTotal, setCompletedTotal] = useState(0);
  const [distinctVersions, setDistinctVersions] = useState<string[]>([]);
  const [customMetricColumns, setCustomMetricColumns] = useState<CustomMetricColumn[]>([]);
  const [projectTags, setProjectTags] = useState<Tag[]>([]);
  const [loading, setLoading] = useState(true);
  const [completedRefreshKey, setCompletedRefreshKey] = useState(0);
  const prevTextRef = useRef({ name: "", sessionId: "" });

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
    return subscribe("experiment_list", (message) => {
      const running = (message.experiments as Experiment[])
        .filter((experiment) => experiment.status === "running" && experiment.project_id === projectId);
      setRunningExperiments(running);
      setCompletedRefreshKey((value) => value + 1);
    });
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    return subscribe("graph_update", (message) => {
      const sessionId = typeof message.session_id === "string" ? message.session_id : "";
      if (!sessionId || !Object.prototype.hasOwnProperty.call(message, "active_runtime_seconds")) return;
      const activeRuntimeSeconds = typeof message.active_runtime_seconds === "number"
        ? message.active_runtime_seconds
        : null;
      setRunningExperiments((previous) => previous.map((experiment) => (
        experiment.session_id === sessionId
          ? { ...experiment, active_runtime_seconds: activeRuntimeSeconds }
          : experiment
      )));
    });
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;

    const previous = prevTextRef.current;
    const textChanged = previous.name !== filters.name.value || previous.sessionId !== filters.sessionId;
    prevTextRef.current = { name: filters.name.value, sessionId: filters.sessionId };

    const controller = new AbortController();
    const delay = textChanged ? 300 : 0;

    const params: {
      limit: number;
      offset: number;
      sort?: string;
      dir?: string;
      name?: string;
      session_id?: string;
      label?: string[];
      tag_id?: string[];
      version?: string[];
      metric_filters?: Record<string, MetricFilter>;
      time_from?: string;
      time_to?: string;
    } = {
      limit: completedRowsPerPage,
      offset: (completedPage - 1) * completedRowsPerPage,
    };
    if (completedSort) {
      params.sort = completedSort.key;
      params.dir = completedSort.direction;
    }
    if (filters.name.value) params.name = filters.name.value;
    if (filters.sessionId) params.session_id = filters.sessionId;
    if (filters.label.size > 0) params.label = Array.from(filters.label);
    if (filters.tags.size > 0) params.tag_id = Array.from(filters.tags);
    if (filters.version.size > 0) params.version = Array.from(filters.version);
    const metricFilters = buildMetricFilterPayload(filters.customMetrics);
    if (Object.keys(metricFilters).length > 0) params.metric_filters = metricFilters;
    if (filters.startTime.from) params.time_from = toUtcFilterTimestamp(filters.startTime.from, false);
    if (filters.startTime.to) params.time_to = toUtcFilterTimestamp(filters.startTime.to, true);

    const timer = window.setTimeout(async () => {
      try {
        const [response, tags] = await Promise.all([
          fetchProjectExperiments(projectId, params, controller.signal),
          fetchProjectTags(projectId),
        ]);
        setRunningExperiments(response.running);
        setCompletedExperiments(response.finished);
        setCompletedTotal(response.finished_total);
        setDistinctVersions(response.distinct_versions);
        setCustomMetricColumns(response.custom_metric_columns);
        setProjectTags(tags);
      } catch (error: unknown) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        console.error("Failed to fetch experiments:", error);
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
    completedExperiments,
    completedTotal,
    customMetricColumns,
    distinctVersions,
    loading,
    projectName,
    projectTags,
    runningExperiments,
  };
}
