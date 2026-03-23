import { useCallback, useEffect, useRef, useState } from "react";
import { fetchProject, fetchProjectExperiments } from "../api";
import type { Experiment } from "../api";
import { subscribe } from "../serverEvents";
import type { Filters } from "../projectFilters";

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
      success?: string[];
      version?: string[];
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
    if (filters.success.size > 0) params.success = Array.from(filters.success);
    if (filters.version.size > 0) params.version = Array.from(filters.version);
    if (filters.startTime.from) params.time_from = filters.startTime.from;
    if (filters.startTime.to) params.time_to = filters.startTime.to;

    const timer = window.setTimeout(async () => {
      try {
        const response = await fetchProjectExperiments(projectId, params, controller.signal);
        setRunningExperiments(response.running);
        setCompletedExperiments(response.finished);
        setCompletedTotal(response.finished_total);
        setDistinctVersions(response.distinct_versions);
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
    distinctVersions,
    loading,
    projectName,
    runningExperiments,
  };
}
