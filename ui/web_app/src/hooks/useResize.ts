import { useCallback, useRef } from "react";

/**
 * Hook for drag-to-resize panels.
 * Returns an onMouseDown handler for a resize handle element.
 *
 * @param direction - "horizontal" resizes left/right, "vertical" resizes top/bottom
 * @param onResize - called with the pixel delta during drag
 * @param onResizeEnd - called when the drag finishes
 */
export function useResize(
  direction: "horizontal" | "vertical",
  onResize: (delta: number) => void,
  onResizeEnd?: () => void,
) {
  const startPos = useRef(0);

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      startPos.current = direction === "horizontal" ? e.clientX : e.clientY;
      document.body.style.cursor = direction === "horizontal" ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";

      const onMouseMove = (ev: MouseEvent) => {
        const current = direction === "horizontal" ? ev.clientX : ev.clientY;
        const delta = current - startPos.current;
        startPos.current = current;
        onResize(delta);
      };

      const onMouseUp = () => {
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        onResizeEnd?.();
      };

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [direction, onResize, onResizeEnd],
  );

  return onMouseDown;
}
