import { useState, useCallback, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Maximize2, Minimize2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ExpandablePanelProps {
  children: ReactNode;
  title?: string;
  className?: string;
  expandButtonClassName?: string;
  onExpandChange?: (expanded: boolean) => void;
}

export function ExpandablePanel({
  children,
  title,
  className = "",
  expandButtonClassName = "",
  onExpandChange,
}: ExpandablePanelProps) {
  const [expanded, setExpanded] = useState(false);

  const toggle = useCallback(() => {
    setExpanded((prev) => {
      const next = !prev;
      onExpandChange?.(next);
      return next;
    });
  }, [onExpandChange]);

  useEffect(() => {
    if (!expanded) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setExpanded(false);
        onExpandChange?.(false);
      }
    };
    document.addEventListener("keydown", handleEsc);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleEsc);
      document.body.style.overflow = "";
    };
  }, [expanded, onExpandChange]);

  const expandButton = (
    <Button
      size="icon"
      variant="ghost"
      onClick={toggle}
      title={expanded ? "Exit fullscreen (Esc)" : "Fullscreen"}
      className={expandButtonClassName}
      data-testid="button-expand-panel"
    >
      {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
    </Button>
  );

  if (expanded) {
    return (
      <>
        {expandButton}
        {createPortal(
          <div
            className="fixed inset-0 z-[100] bg-background flex flex-col"
            data-testid="expanded-panel-overlay"
          >
            <div className="flex items-center justify-between px-4 py-2 border-b bg-background shrink-0">
              <span className="text-sm font-medium truncate">
                {title || "Expanded View"}
              </span>
              <Button
                size="icon"
                variant="ghost"
                onClick={toggle}
                title="Exit fullscreen (Esc)"
                data-testid="button-collapse-panel"
              >
                <Minimize2 className="w-4 h-4" />
              </Button>
            </div>
            <div className={`flex-1 overflow-auto ${className}`}>
              {children}
            </div>
          </div>,
          document.body
        )}
      </>
    );
  }

  return expandButton;
}

interface ExpandableContentProps {
  children: ReactNode;
  title?: string;
  className?: string;
  contentClassName?: string;
  headerExtra?: ReactNode;
}

export function ExpandableContent({
  children,
  title,
  className = "",
  contentClassName = "",
  headerExtra,
}: ExpandableContentProps) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    document.addEventListener("keydown", handleEsc);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleEsc);
      document.body.style.overflow = "";
    };
  }, [expanded]);

  if (expanded) {
    return createPortal(
      <div
        className="fixed inset-0 z-[100] bg-background flex flex-col"
        data-testid="expanded-content-overlay"
      >
        <div className="flex items-center justify-between px-4 py-2 border-b bg-background shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-medium truncate">
              {title || "Expanded View"}
            </span>
            {headerExtra}
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setExpanded(false)}
              title="Exit fullscreen (Esc)"
              data-testid="button-collapse-content"
            >
              <Minimize2 className="w-4 h-4" />
            </Button>
          </div>
        </div>
        <div className={`flex-1 overflow-auto ${contentClassName}`}>
          {children}
        </div>
      </div>,
      document.body
    );
  }

  return (
    <div className={className}>
      <div className="relative">
        <Button
          size="icon"
          variant="ghost"
          onClick={() => setExpanded(true)}
          title="Fullscreen"
          className="absolute top-2 right-2 z-10"
          data-testid="button-expand-content"
        >
          <Maximize2 className="w-4 h-4" />
        </Button>
        {children}
      </div>
    </div>
  );
}
