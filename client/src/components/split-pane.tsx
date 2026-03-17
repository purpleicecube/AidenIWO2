import { useState, useRef, useCallback, useEffect, type ReactNode } from "react";

export interface PaneConfig {
  defaultSize: number;
  minSize?: number;
  maxSize?: number;
}

interface SplitPaneProps {
  children: ReactNode[];
  panes: PaneConfig[];
  storageKey?: string;
  direction?: "horizontal" | "vertical";
  gutterSize?: number;
  collapseMobileAt?: number;
}

const GUTTER_SIZE = 8;

function loadSizes(key: string, count: number): number[] | null {
  try {
    const raw = localStorage.getItem(`splitpane:${key}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length === count && parsed.every((v: any) => typeof v === "number" && v > 0)) {
      return parsed;
    }
  } catch {}
  return null;
}

function saveSizes(key: string, sizes: number[]) {
  try {
    localStorage.setItem(`splitpane:${key}`, JSON.stringify(sizes.map((s) => Math.round(s * 100) / 100)));
  } catch {}
}

export default function SplitPane({
  children,
  panes,
  storageKey,
  direction = "horizontal",
  gutterSize = GUTTER_SIZE,
  collapseMobileAt = 768,
}: SplitPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    gutterIndex: number;
    startPos: number;
    startSizes: number[];
    containerSize: number;
  } | null>(null);

  const childArray = Array.isArray(children) ? children : [children];
  const paneCount = Math.min(childArray.length, panes.length);

  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" ? window.innerWidth < collapseMobileAt : false
  );

  const getInitialSizes = useCallback((): number[] => {
    if (storageKey) {
      const saved = loadSizes(storageKey, paneCount);
      if (saved) return saved;
    }
    return panes.slice(0, paneCount).map((p) => p.defaultSize);
  }, [storageKey, paneCount, panes]);

  const [sizes, setSizes] = useState<number[]>(getInitialSizes);

  useEffect(() => {
    if (sizes.length !== paneCount) {
      setSizes(getInitialSizes());
    }
  }, [paneCount, sizes.length, getInitialSizes]);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < collapseMobileAt);
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [collapseMobileAt]);

  const clampPair = useCallback(
    (sizeA: number, sizeB: number, idxA: number, idxB: number): [number, number] => {
      const total = sizeA + sizeB;
      const cfgA = panes[idxA];
      const cfgB = panes[idxB];
      let a = sizeA;
      let b = sizeB;

      if (cfgA.minSize !== undefined && a < cfgA.minSize) a = cfgA.minSize;
      if (cfgA.maxSize !== undefined && a > cfgA.maxSize) a = cfgA.maxSize;
      b = total - a;

      if (cfgB.minSize !== undefined && b < cfgB.minSize) { b = cfgB.minSize; a = total - b; }
      if (cfgB.maxSize !== undefined && b > cfgB.maxSize) { b = cfgB.maxSize; a = total - b; }

      return [a, b];
    },
    [panes]
  );

  const handleGutterMouseDown = useCallback(
    (gutterIndex: number, e: React.MouseEvent | React.TouchEvent) => {
      e.preventDefault();

      const container = containerRef.current;
      if (!container) return;

      const isHoriz = direction === "horizontal";
      const containerSize = isHoriz ? container.offsetWidth : container.offsetHeight;
      const totalGutter = (paneCount - 1) * gutterSize;
      const usableSize = containerSize - totalGutter;

      if (usableSize <= 0) return;

      const startPos =
        "touches" in e
          ? isHoriz ? e.touches[0].clientX : e.touches[0].clientY
          : isHoriz ? e.clientX : e.clientY;

      dragRef.current = {
        gutterIndex,
        startPos,
        startSizes: [...sizes],
        containerSize: usableSize,
      };

      document.body.style.cursor = isHoriz ? "col-resize" : "row-resize";
      document.body.style.userSelect = "none";

      const handleMove = (ev: MouseEvent | TouchEvent) => {
        if (!dragRef.current) return;

        const currentPos =
          "touches" in ev
            ? isHoriz ? ev.touches[0].clientX : ev.touches[0].clientY
            : isHoriz ? ev.clientX : ev.clientY;

        const pixelDelta = currentPos - dragRef.current.startPos;
        const totalWeight = dragRef.current.startSizes.reduce((a, b) => a + b, 0);
        const percentDelta = (pixelDelta / dragRef.current.containerSize) * totalWeight;

        const gi = dragRef.current.gutterIndex;
        const newA = dragRef.current.startSizes[gi] + percentDelta;
        const newB = dragRef.current.startSizes[gi + 1] - percentDelta;

        const [clampedA, clampedB] = clampPair(newA, newB, gi, gi + 1);

        const newSizes = [...dragRef.current.startSizes];
        newSizes[gi] = clampedA;
        newSizes[gi + 1] = clampedB;

        setSizes(newSizes);
      };

      const handleEnd = () => {
        dragRef.current = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        document.removeEventListener("mousemove", handleMove);
        document.removeEventListener("mouseup", handleEnd);
        document.removeEventListener("touchmove", handleMove);
        document.removeEventListener("touchend", handleEnd);
      };

      document.addEventListener("mousemove", handleMove);
      document.addEventListener("mouseup", handleEnd);
      document.addEventListener("touchmove", handleMove, { passive: false });
      document.addEventListener("touchend", handleEnd);
    },
    [sizes, direction, clampPair, paneCount, gutterSize]
  );

  useEffect(() => {
    if (storageKey && sizes.length === paneCount) {
      saveSizes(storageKey, sizes);
    }
  }, [sizes, storageKey, paneCount]);

  if (isMobile) {
    return (
      <div
        className={`flex ${direction === "horizontal" ? "flex-col" : "flex-row"} h-full w-full`}
        data-testid="split-pane-mobile"
      >
        {childArray.slice(0, paneCount).map((child, i) => (
          <div key={i} className="flex-1 min-h-0 min-w-0 overflow-auto">
            {child}
          </div>
        ))}
      </div>
    );
  }

  const isHorizontal = direction === "horizontal";
  const totalGutterSpace = (paneCount - 1) * gutterSize;
  const totalWeight = sizes.reduce((a, b) => a + b, 0);

  return (
    <div
      ref={containerRef}
      className={`flex ${isHorizontal ? "flex-row" : "flex-col"} h-full w-full`}
      data-testid="split-pane-container"
    >
      {childArray.slice(0, paneCount).map((child, i) => {
        const pct = (sizes[i] / totalWeight) * 100;
        const gutterShare = (totalGutterSpace * sizes[i]) / totalWeight;
        return (
          <div key={i} className="contents">
            <div
              className="overflow-auto min-w-0 min-h-0 flex flex-col"
              style={{
                [isHorizontal ? "width" : "height"]: `calc(${pct}% - ${gutterShare}px)`,
                flexShrink: 0,
                flexGrow: 0,
              }}
              data-testid={`split-pane-panel-${i}`}
            >
              {child}
            </div>

            {i < paneCount - 1 && (
              <div
                className={`
                  flex-shrink-0 flex items-center justify-center
                  ${isHorizontal ? "cursor-col-resize" : "cursor-row-resize"}
                  bg-border hover:bg-primary/20 active:bg-primary/30
                  transition-colors duration-150
                  group
                `}
                style={{
                  [isHorizontal ? "width" : "height"]: `${gutterSize}px`,
                }}
                onMouseDown={(e) => handleGutterMouseDown(i, e)}
                onTouchStart={(e) => handleGutterMouseDown(i, e)}
                data-testid={`split-pane-gutter-${i}`}
                role="separator"
                aria-orientation={isHorizontal ? "vertical" : "horizontal"}
              >
                <div
                  className={`
                    rounded-full bg-muted-foreground/40 group-hover:bg-primary/60 group-active:bg-primary
                    transition-colors duration-150
                    ${isHorizontal ? "w-[4px] h-10" : "h-[4px] w-10"}
                  `}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
