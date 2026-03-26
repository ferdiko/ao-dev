import { useCallback, useEffect, useRef, useState } from "react";
import { NODE_H, NODE_W, type GraphLayoutResult } from "../graphLayout";

export interface GraphFocusApiHandle {
  setCenter: (x: number, y: number, options?: { zoom?: number; duration?: number }) => void;
}

export function useRunGraphFocus({
  graphLayout,
  sortedNodeIds,
}: {
  graphLayout: GraphLayoutResult;
  sortedNodeIds: string[];
}) {
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const nodeRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const graphApiRef = useRef<GraphFocusApiHandle | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const prevNodeCountRef = useRef(0);
  const focusedRef = useRef<string | null>(null);

  useEffect(() => {
    focusedRef.current = focusedNodeId;
  }, [focusedNodeId]);

  const scrollToNode = useCallback((nodeId: string) => {
    const element = nodeRefs.current.get(nodeId);
    if (!element) return;
    const scrollParent = element.closest(".run-detail-io-scroll") as HTMLElement | null;
    if (!scrollParent) return;

    const marginTop = parseInt(getComputedStyle(element).marginTop, 10) || 0;
    scrollParent.scrollTop = element.offsetTop - scrollParent.offsetTop - marginTop;
  }, []);

  const focusNodeByIndex = useCallback((index: number) => {
    const api = graphApiRef.current;
    if (!api || !sortedNodeIds.length) return;

    const clampedIndex = Math.max(0, Math.min(sortedNodeIds.length - 1, index));
    const nodeId = sortedNodeIds[clampedIndex];
    const position = graphLayout.positions.get(nodeId);
    if (!position) return;

    api.setCenter(position.x + NODE_W / 2, position.y + NODE_H / 2, { zoom: 1, duration: 300 });
    setFocusedNodeId(nodeId);
    scrollToNode(nodeId);
  }, [graphLayout, scrollToNode, sortedNodeIds]);

  const focusNodeById = useCallback((nodeId: string) => {
    const index = sortedNodeIds.indexOf(nodeId);
    if (index >= 0) focusNodeByIndex(index);
  }, [focusNodeByIndex, sortedNodeIds]);

  useEffect(() => {
    if (!sortedNodeIds.length) return;
    if (sortedNodeIds.length === prevNodeCountRef.current) return;

    prevNodeCountRef.current = sortedNodeIds.length;
    const lastNodeId = sortedNodeIds[sortedNodeIds.length - 1];
    const position = graphLayout.positions.get(lastNodeId);
    if (!position) return;

    const centerX = position.x + NODE_W / 2;
    const centerY = position.y + NODE_H / 2;
    setFocusedNodeId(lastNodeId);

    let attempts = 0;
    const tryCenter = () => {
      if (attempts++ >= 50) return;
      const api = graphApiRef.current;
      if (!api) {
        requestAnimationFrame(tryCenter);
        return;
      }

      api.setCenter(centerX, centerY, { zoom: 1, duration: 0 });
      requestAnimationFrame(() => {
        const element = nodeRefs.current.get(lastNodeId);
        if (!element) return;
        const scrollParent = element.closest(".run-detail-io-scroll") as HTMLElement | null;
        if (!scrollParent) return;

        const marginTop = parseInt(getComputedStyle(element).marginTop, 10) || 0;
        scrollParent.scrollTo({
          top: element.offsetTop - scrollParent.offsetTop - marginTop,
          behavior: "instant",
        });
      });
    };

    requestAnimationFrame(tryCenter);
  }, [graphLayout, sortedNodeIds]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let cooldownUntil = 0;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const now = performance.now();
      if (now < cooldownUntil) return;
      if (Math.abs(event.deltaY) < 4) return;

      const direction = event.deltaY > 0 ? 1 : -1;
      const currentIndex = sortedNodeIds.indexOf(focusedRef.current ?? "");
      focusNodeByIndex(currentIndex + direction);
      cooldownUntil = now + 1000;
    };

    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      canvas.removeEventListener("wheel", onWheel);
    };
  }, [focusNodeByIndex, sortedNodeIds]);

  useEffect(() => {
    let cooldownUntil = 0;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      const tagName = (event.target as HTMLElement)?.tagName;
      if (tagName === "INPUT" || tagName === "TEXTAREA") return;

      event.preventDefault();
      const now = performance.now();
      if (now < cooldownUntil) return;

      const direction = event.key === "ArrowDown" ? 1 : -1;
      const currentIndex = sortedNodeIds.indexOf(focusedRef.current ?? "");
      focusNodeByIndex(currentIndex + direction);
      cooldownUntil = now + 300;
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [focusNodeByIndex, sortedNodeIds]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const observer = new ResizeObserver(() => {
      const api = graphApiRef.current;
      const nodeId = focusedRef.current;
      if (!api || !nodeId) return;

      const position = graphLayout.positions.get(nodeId);
      if (!position) return;
      api.setCenter(position.x + NODE_W / 2, position.y + NODE_H / 2, { zoom: 1, duration: 0 });
    });

    observer.observe(canvas);
    return () => observer.disconnect();
  }, [graphLayout]);

  return {
    canvasRef,
    focusNodeById,
    focusedNodeId,
    graphApiRef,
    nodeRefs,
  };
}
