import { useCallback, useEffect, useState } from "react";
import {
  createProjectTag,
  deleteProjectTag,
  fetchProjectTags,
} from "../projectsApi";
import { updateRunTags } from "../runsApi";
import { prefetchTrace } from "../traceChatApi";
import type { Tag } from "../tags";
import { sortTagsByName } from "../tags";
import { useRunState } from "./useRunState";

export function useRunWorkspace({
  projectId,
  runId,
}: {
  projectId?: string;
  runId: string;
}) {
  const runState = useRunState(runId);
  const {
    refreshRunDetail,
    runTags,
  } = runState;
  const [selectedTagsOverride, setSelectedTagsOverride] = useState<Tag[] | null>(null);
  const [projectTags, setProjectTags] = useState<Tag[]>([]);
  const [tagPendingDelete, setTagPendingDelete] = useState<Tag | null>(null);
  const [deletingTag, setDeletingTag] = useState(false);
  const [deleteTagError, setDeleteTagError] = useState<string | null>(null);
  const selectedTags = selectedTagsOverride ?? runTags;

  useEffect(() => {
    prefetchTrace(runId);
  }, [runId]);

  useEffect(() => {
    if (!projectId) {
      setProjectTags([]);
      return;
    }

    let cancelled = false;
    fetchProjectTags(projectId)
      .then((tags) => {
        if (!cancelled) {
          setProjectTags(sortTagsByName(tags));
        }
      })
      .catch((error) => {
        if (!cancelled) {
          console.error("Failed to load project tags:", error);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const reloadTags = useCallback(async () => {
    if (!projectId) {
      return;
    }

    const [tags] = await Promise.all([
      fetchProjectTags(projectId).then(sortTagsByName),
      refreshRunDetail(),
    ]);
    setProjectTags(tags);
    setSelectedTagsOverride(null);
  }, [projectId, refreshRunDetail]);

  const handleToggleTag = useCallback((tag: Tag) => {
    const alreadySelected = selectedTags.some((item) => item.tag_id === tag.tag_id);
    const nextTags = sortTagsByName(
      alreadySelected
        ? selectedTags.filter((item) => item.tag_id !== tag.tag_id)
        : [...selectedTags, tag],
    );
    setSelectedTagsOverride(nextTags);
    updateRunTags(runId, nextTags.map((item) => item.tag_id))
      .catch(async (error) => {
        console.error("Failed to update run tags:", error);
        await reloadTags().catch(console.error);
      });
  }, [reloadTags, runId, selectedTags]);

  const handleCreateTag = useCallback((name: string, color: string) => {
    if (!projectId) {
      return;
    }

    createProjectTag(projectId, name, color)
      .then(async (tag) => {
        const nextProjectTags = sortTagsByName([...projectTags, tag]);
        const nextSelectedTags = sortTagsByName([...selectedTags, tag]);
        setProjectTags(nextProjectTags);
        setSelectedTagsOverride(nextSelectedTags);
        await updateRunTags(runId, nextSelectedTags.map((item) => item.tag_id));
      })
      .catch(async (error) => {
        console.error("Failed to create tag:", error);
        await reloadTags().catch(console.error);
      });
  }, [projectId, projectTags, reloadTags, runId, selectedTags]);

  const openDeleteTagModal = useCallback((tag: Tag) => {
    setDeleteTagError(null);
    setTagPendingDelete(tag);
  }, []);

  const closeDeleteTagModal = useCallback(() => {
    if (deletingTag) {
      return;
    }

    setTagPendingDelete(null);
    setDeleteTagError(null);
  }, [deletingTag]);

  const confirmDeleteTag = useCallback(async () => {
    if (!projectId || !tagPendingDelete) {
      return;
    }

    setDeleteTagError(null);
    setDeletingTag(true);
    try {
      await deleteProjectTag(projectId, tagPendingDelete.tag_id);
      setProjectTags((previous) => previous.filter((item) => item.tag_id !== tagPendingDelete.tag_id));
      setSelectedTagsOverride((previous) => (previous ?? runTags).filter((item) => item.tag_id !== tagPendingDelete.tag_id));
      setTagPendingDelete(null);
    } catch (error) {
      console.error("Failed to delete tag:", error);
      setDeleteTagError(error instanceof Error ? error.message : "Failed to delete tag.");
      await reloadTags().catch(console.error);
    } finally {
      setDeletingTag(false);
    }
  }, [projectId, reloadTags, runTags, tagPendingDelete]);

  return {
    ...runState,
    closeDeleteTagModal,
    confirmDeleteTag,
    deleteTagError,
    deletingTag,
    handleCreateTag,
    handleToggleTag,
    openDeleteTagModal,
    projectTags,
    selectedTags,
    tagPendingDelete,
  };
}
