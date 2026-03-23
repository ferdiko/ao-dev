import { useEffect, useState } from "react";

export interface RunViewLayoutState {
  graphWidth: number;
  chatWidth: number;
  chatCollapsed: boolean;
}

const DEFAULT_RUN_VIEW_LAYOUT: RunViewLayoutState = {
  graphWidth: 340,
  chatWidth: 340,
  chatCollapsed: false,
};

const RUN_VIEW_LAYOUT_STORAGE_KEY = "web_app:run_view_layout";

function loadRunViewLayout(): RunViewLayoutState {
  try {
    const raw = localStorage.getItem(RUN_VIEW_LAYOUT_STORAGE_KEY);
    if (!raw) return DEFAULT_RUN_VIEW_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<RunViewLayoutState>;
    return {
      graphWidth: typeof parsed.graphWidth === "number" ? parsed.graphWidth : DEFAULT_RUN_VIEW_LAYOUT.graphWidth,
      chatWidth: typeof parsed.chatWidth === "number" ? parsed.chatWidth : DEFAULT_RUN_VIEW_LAYOUT.chatWidth,
      chatCollapsed: typeof parsed.chatCollapsed === "boolean" ? parsed.chatCollapsed : DEFAULT_RUN_VIEW_LAYOUT.chatCollapsed,
    };
  } catch {
    return DEFAULT_RUN_VIEW_LAYOUT;
  }
}

export function useRunViewLayout() {
  const [layoutState, setLayoutState] = useState<RunViewLayoutState>(loadRunViewLayout);

  useEffect(() => {
    localStorage.setItem(RUN_VIEW_LAYOUT_STORAGE_KEY, JSON.stringify(layoutState));
  }, [layoutState]);

  return [layoutState, setLayoutState] as const;
}
