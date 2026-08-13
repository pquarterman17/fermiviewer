import {
  forwardRef,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import type uPlot from "uplot";

import { svgToPngBlob } from "../../lib/charts/chartRaster";
import { chartToSvg, specFromUplot } from "../../lib/charts/chartSvg";
import { useViewer } from "../../store/viewer";

/** Swap a filename's extension, or append one if there wasn't a recognised
 *  image extension to swap (defensive — every caller today passes a
 *  ".png" filename). */
function withExtension(filename: string, ext: string): string {
  return /\.(png|jpg|jpeg)$/i.test(filename)
    ? filename.replace(/\.(png|jpg|jpeg)$/i, ext)
    : `${filename}${ext}`;
}

/** Insert a "-300dpi" style suffix before the extension. */
function withDpiSuffix(filename: string, dpi: number): string {
  return withExtension(filename, `-${dpi}dpi.png`);
}

interface MenuPoint {
  x: number;
  y: number;
}

interface PlotContextSurfaceProps {
  plotRef: React.RefObject<uPlot | null>;
  label: string;
  filename: string;
  shellClassName?: string;
  className?: string;
  style?: React.CSSProperties;
  onExportData?: () => void;
  exportLabel?: string;
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("the plot canvas could not be encoded"));
    }, "image/png");
  });
}

const PlotContextSurface = forwardRef<
  HTMLDivElement,
  PlotContextSurfaceProps
>(function PlotContextSurface(
  {
    plotRef,
    label,
    filename,
    shellClassName,
    className,
    style,
    onExportData,
    exportLabel = "Export data CSV",
  },
  hostRef,
) {
  const shellRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const firstItemRef = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState<MenuPoint | null>(null);

  useEffect(() => {
    if (menu) requestAnimationFrame(() => firstItemRef.current?.focus());
  }, [menu]);

  const openAt = (x: number, y: number) => {
    setMenu({
      x: Math.min(x, Math.max(8, window.innerWidth - 210)),
      // taller now: 6 items (up from 3) before the optional export-data row
      y: Math.min(y, Math.max(8, window.innerHeight - 260)),
    });
  };

  const onContextMenu = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    openAt(event.clientX, event.clientY);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
      event.preventDefault();
      const rect = shellRef.current?.getBoundingClientRect();
      openAt(rect?.left ?? 8, rect?.top ?? 8);
    } else if (event.key === "Escape" && menu) {
      event.preventDefault();
      setMenu(null);
      shellRef.current?.focus();
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>(
        '[role="menuitem"]:not([disabled])',
      ) ?? [],
    );
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    let next: number | null = null;
    if (event.key === "ArrowDown") next = index + 1;
    else if (event.key === "ArrowUp") next = index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else if (event.key === "Tab") {
      setMenu(null);
      return;
    } else {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (items.length > 0 && next !== null) {
      items[(next + items.length) % items.length]?.focus();
    }
  };

  const plotCanvas = () =>
    shellRef.current?.querySelector("canvas") ?? null;

  const report = (message: string) => useViewer.getState().setStatus(message);

  const reset = () => {
    const plot = plotRef.current;
    const x = plot?.data[0];
    if (plot && x && x.length > 0) {
      plot.setScale("x", { min: x[0] as number, max: x[x.length - 1] as number });
    }
    setMenu(null);
  };

  const copy = async () => {
    try {
      const canvas = plotCanvas();
      if (!canvas) throw new Error("plot canvas is unavailable");
      const blob = await canvasBlob(canvas);
      await navigator.clipboard.write([
        new ClipboardItem({ "image/png": blob }),
      ]);
      report(`${label}: copied plot`);
    } catch (error) {
      report(`${label}: ${error instanceof Error ? error.message : "copy failed"}`);
    }
    setMenu(null);
  };

  const save = async () => {
    try {
      const canvas = plotCanvas();
      if (!canvas) throw new Error("plot canvas is unavailable");
      const blob = await canvasBlob(canvas);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      report(`${label}: saved ${filename}`);
    } catch (error) {
      report(`${label}: ${error instanceof Error ? error.message : "save failed"}`);
    }
    setMenu(null);
  };

  // Vector + high-DPI export (ANALYSIS_PRESENTATION_PLAN item 4): built once
  // from the live uPlot instance's PUBLIC state via lib/charts/chartSvg.ts,
  // so every chart wrapped in this surface gets it with no per-chart wiring.
  const downloadBlob = (blob: Blob, name: string) => {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const exportSvg = () => {
    try {
      const plot = plotRef.current;
      if (!plot) throw new Error("plot is unavailable");
      const svg = chartToSvg(specFromUplot(plot, { title: label }));
      const name = withExtension(filename, ".svg");
      downloadBlob(new Blob([svg], { type: "image/svg+xml" }), name);
      report(`${label}: saved ${name}`);
    } catch (error) {
      report(`${label}: ${error instanceof Error ? error.message : "SVG export failed"}`);
    }
    setMenu(null);
  };

  const exportPngAtDpi = async (dpi: number) => {
    try {
      const plot = plotRef.current;
      if (!plot) throw new Error("plot is unavailable");
      const svg = chartToSvg(specFromUplot(plot, { title: label }));
      const blob = await svgToPngBlob(svg, dpi / 96);
      const name = withDpiSuffix(filename, dpi);
      downloadBlob(blob, name);
      report(`${label}: saved ${name}`);
    } catch (error) {
      report(`${label}: ${error instanceof Error ? error.message : `${dpi} dpi export failed`}`);
    }
    setMenu(null);
  };

  return (
    <div
      ref={shellRef}
      className={`fvd-plot-context-surface${shellClassName ? ` ${shellClassName}` : ""}`}
      tabIndex={0}
      aria-label={`${label} plot`}
      onContextMenu={onContextMenu}
      onKeyDown={onKeyDown}
    >
      <div ref={hostRef} className={className} style={style} />
      {menu && (
        <>
          <div
            className="fvd-ctx-backdrop"
            onPointerDown={() => setMenu(null)}
            onContextMenu={(event) => {
              event.preventDefault();
              setMenu(null);
            }}
          />
          <div
            ref={menuRef}
            className="fvd-ctx-menu fvd-glass"
            style={{ left: menu.x, top: menu.y }}
            role="menu"
            aria-label={`${label} plot actions`}
            onKeyDown={onMenuKeyDown}
          >
            <button
              ref={firstItemRef}
              className="fvd-ctx-item"
              role="menuitem"
              onClick={reset}
            >
              Reset view
            </button>
            <button
              className="fvd-ctx-item"
              role="menuitem"
              onClick={() => void copy()}
            >
              Copy plot
            </button>
            <button
              className="fvd-ctx-item"
              role="menuitem"
              onClick={() => void save()}
            >
              Save plot PNG (screen)
            </button>
            <button
              className="fvd-ctx-item"
              role="menuitem"
              disabled={!plotRef.current}
              onClick={exportSvg}
            >
              Export SVG (vector)
            </button>
            <button
              className="fvd-ctx-item"
              role="menuitem"
              disabled={!plotRef.current}
              onClick={() => void exportPngAtDpi(300)}
            >
              Export PNG (300 dpi)
            </button>
            <button
              className="fvd-ctx-item"
              role="menuitem"
              disabled={!plotRef.current}
              onClick={() => void exportPngAtDpi(600)}
            >
              Export PNG (600 dpi)
            </button>
            {onExportData && (
              <>
                <div className="fvd-ctx-sep" role="separator" />
                <button
                  className="fvd-ctx-item"
                  role="menuitem"
                  onClick={() => {
                    setMenu(null);
                    onExportData();
                  }}
                >
                  {exportLabel}
                </button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
});

export default PlotContextSurface;
