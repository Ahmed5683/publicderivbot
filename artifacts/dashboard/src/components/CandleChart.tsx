import { useRef, useEffect, useState, useCallback } from "react";
import type { Candle, FractalMarker } from "@workspace/api-client-react";

interface CandleChartProps {
  candles:         Candle[];
  markers?:        FractalMarker[];
  sphLevel?:       number | null;
  splLevel?:       number | null;
  cocLevel?:       number | null;
  trend?:          string;
  tsiValues?:      number[];
  momentumValues?: number[];
}

const C = {
  bg:       "#0d1117",
  panel:    "#0f172a",
  grid:     "rgba(255,255,255,0.04)",
  axis:     "rgba(255,255,255,0.10)",
  text:     "#6b7280",
  textBrt:  "#9ca3af",
  bull:     "#22c55e",
  bear:     "#ef4444",
  tsiLine:  "#00d4ff",
  momLine:  "#f59e0b",
  cocColor: "#a78bfa",
  scrollBg: "rgba(255,255,255,0.08)",
  scrollFg: "rgba(255,255,255,0.30)",
};

const VISIBLE  = 300;
const RIGHT    = 120;
const SCROLL_H = 18; // taller for touch targets
const BOTTOM   = SCROLL_H + 22;

function mapY(v: number, lo: number, hi: number, top: number, h: number) {
  if (hi === lo) return top + h / 2;
  return top + ((hi - v) / (hi - lo)) * h;
}

export function CandleChart({
  candles,
  sphLevel, splLevel, cocLevel,
  trend = "",
  tsiValues = [],
  momentumValues = [],
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const [hoverIdx, setHoverIdx]         = useState<number | null>(null);
  const [scrollOffset, setScrollOffset] = useState(0);

  // Refs so event handlers never read stale closures
  const scrollOffRef   = useRef(0);
  const maxOffRef      = useRef(0);
  const nRef           = useRef(0);
  const totalRef       = useRef(0);

  // Drag state
  const dragMode       = useRef<"none" | "chart" | "scrollbar">("none");
  const dragStartX     = useRef(0);
  const dragStartOff   = useRef(0);

  const total  = candles.length;
  const maxOff = Math.max(0, total - VISIBLE);
  maxOffRef.current = maxOff;
  totalRef.current  = total;

  const clampedOff = Math.min(Math.max(scrollOffset, 0), maxOff);
  scrollOffRef.current = clampedOff;

  const start   = Math.max(0, total - VISIBLE - clampedOff);
  const visible = candles.slice(start, start + VISIBLE);
  const n       = visible.length;
  nRef.current  = n;

  // TSI / Momentum — arrays cover the last tsiLen candles of the full dataset
  const tsiLen = tsiValues.length;
  const momLen = momentumValues.length;
  const visStart = start;
  const visEnd   = start + n;

  const tsiCandleStart  = total - tsiLen;
  const overlapTsiStart = Math.max(visStart, tsiCandleStart);
  const overlapTsiEnd   = Math.min(visEnd, total);
  const vTsi = overlapTsiStart < overlapTsiEnd
    ? tsiValues.slice(overlapTsiStart - tsiCandleStart, overlapTsiEnd - tsiCandleStart)
    : [];
  const tsiVisOff = overlapTsiStart - visStart;

  const momCandleStart  = total - momLen;
  const overlapMomStart = Math.max(visStart, momCandleStart);
  const overlapMomEnd   = Math.min(visEnd, total);
  const vMom = overlapMomStart < overlapMomEnd
    ? momentumValues.slice(overlapMomStart - momCandleStart, overlapMomEnd - momCandleStart)
    : [];
  const momVisOff = overlapMomStart - visStart;

  const hasTsi = vTsi.length > 0;
  const hasMom = vMom.length > 0;

  // ── Helpers shared between draw and event handlers ──────────
  const getLayout = useCallback((W: number, H: number) => {
    const subCount  = (hasTsi ? 1 : 0) + (hasMom ? 1 : 0);
    const subPanelH = subCount === 2 ? 240 : subCount === 1 ? 120 : 0;
    const eachSub   = subPanelH / Math.max(subCount, 1);
    const MAIN_TOP  = 10;
    const MAIN_H    = H - BOTTOM - 10 - subPanelH - (subPanelH > 0 ? 8 : 0);
    const chartW    = W - RIGHT;
    return { subCount, subPanelH, eachSub, MAIN_TOP, MAIN_H, chartW };
  }, [hasTsi, hasMom]);

  const getScrollbarGeom = useCallback((W: number, H: number, nn: number, tot: number, off: number, mo: number) => {
    const { chartW } = getLayout(W, H);
    const BAR_Y  = H - SCROLL_H + 1;
    const BAR_W  = chartW - 4;
    const thumbW = Math.max((VISIBLE / Math.max(tot, 1)) * BAR_W, 28);
    const thumbX = 2 + (mo > 0 ? (1 - off / mo) * (BAR_W - thumbW) : 0);
    return { BAR_Y, BAR_W, thumbW, thumbX };
  }, [getLayout]);

  const isOnScrollbar = useCallback((clientY: number, rect: DOMRect, H: number) => {
    const localY = clientY - rect.top;
    return localY >= H - SCROLL_H;
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const cont   = containerRef.current;
    if (!canvas || !cont || n === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const W   = cont.clientWidth;
    const H   = cont.clientHeight;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width  = W + "px";
    canvas.style.height = H + "px";

    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);

    const { eachSub, MAIN_TOP, MAIN_H, chartW } = getLayout(W, H);
    const cw = chartW / n;
    const bw = Math.max(cw * 0.6, 1);

    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    // ── Level lines ───────────────────────────────────────────
    type LevelEntry = { label: string; price: number; color: string; dash: number[] };
    const levels: LevelEntry[] = [];
    if (trend === "UPTREND") {
      if (sphLevel != null) levels.push({ label: "SPH", price: sphLevel, color: C.bull, dash: [] });
      if (cocLevel != null) levels.push({ label: "CoC", price: cocLevel, color: C.cocColor, dash: [5, 4] });
    } else if (trend === "DOWNTREND") {
      if (splLevel != null) levels.push({ label: "SPL", price: splLevel, color: C.bear, dash: [] });
      if (cocLevel != null) levels.push({ label: "CoC", price: cocLevel, color: C.cocColor, dash: [5, 4] });
    } else {
      if (sphLevel != null) levels.push({ label: "SPH", price: sphLevel, color: C.bull, dash: [] });
      if (splLevel != null) levels.push({ label: "SPL", price: splLevel, color: C.bear, dash: [] });
      if (cocLevel != null) levels.push({ label: "CoC", price: cocLevel, color: C.cocColor, dash: [5, 4] });
    }

    const pMax0    = Math.max(...visible.map(c => c.high));
    const pMin0    = Math.min(...visible.map(c => c.low));
    const lvPrices = levels.map(l => l.price);
    const rawMax   = Math.max(pMax0, ...lvPrices);
    const rawMin   = Math.min(pMin0, ...lvPrices);
    const pad      = (rawMax - rawMin) * 0.06;
    const pMax     = rawMax + pad;
    const pMin     = rawMin - pad;

    // ── Grid ──────────────────────────────────────────────────
    ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
    const gN = 6;
    for (let i = 0; i <= gN; i++) {
      const y = MAIN_TOP + (MAIN_H / gN) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
    }

    // ── Horizontal levels ─────────────────────────────────────
    for (const { label, price, color, dash } of levels) {
      const y = mapY(price, pMin, pMax, MAIN_TOP, MAIN_H);
      if (y < MAIN_TOP - 4 || y > MAIN_TOP + MAIN_H + 4) continue;
      ctx.strokeStyle = color + "cc";
      ctx.lineWidth   = label === "CoC" ? 1.2 : 1.8;
      ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color; ctx.font = "bold 10px monospace"; ctx.textAlign = "left";
      ctx.fillText(`${label}  ${price.toFixed(4)}`, chartW + 4, y + 3);
    }

    // ── Candles ───────────────────────────────────────────────
    for (let i = 0; i < n; i++) {
      const c      = visible[i];
      const isUp   = c.close >= c.open;
      const col    = isUp ? C.bull : C.bear;
      const cx     = i * cw + cw / 2;
      const highY  = mapY(c.high,  pMin, pMax, MAIN_TOP, MAIN_H);
      const lowY   = mapY(c.low,   pMin, pMax, MAIN_TOP, MAIN_H);
      const openY  = mapY(c.open,  pMin, pMax, MAIN_TOP, MAIN_H);
      const closeY = mapY(c.close, pMin, pMax, MAIN_TOP, MAIN_H);
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.globalAlpha = i === hoverIdx ? 1 : 0.88;
      ctx.beginPath(); ctx.moveTo(cx, highY); ctx.lineTo(cx, lowY); ctx.stroke();
      ctx.fillStyle = col;
      ctx.fillRect(i * cw + (cw - bw) / 2, Math.min(openY, closeY), bw, Math.max(Math.abs(closeY - openY), 1));
      ctx.globalAlpha = 1;
    }

    // ── Crosshair ─────────────────────────────────────────────
    if (hoverIdx !== null && hoverIdx < n) {
      const c  = visible[hoverIdx];
      const cx = hoverIdx * cw + cw / 2;
      ctx.strokeStyle = "rgba(255,255,255,0.18)"; ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(cx, MAIN_TOP); ctx.lineTo(cx, MAIN_TOP + MAIN_H); ctx.stroke();
      ctx.setLineDash([]);
      const closeY = mapY(c.close, pMin, pMax, MAIN_TOP, MAIN_H);
      ctx.fillStyle = c.close >= c.open ? C.bull : C.bear;
      ctx.font = "bold 10px monospace"; ctx.textAlign = "left";
      ctx.fillText(c.close.toFixed(4), chartW + 4, closeY + 3);
    }

    // ── Price axis ────────────────────────────────────────────
    for (let i = 0; i <= gN; i++) {
      const price = pMax - (i / gN) * (pMax - pMin);
      const y     = MAIN_TOP + (MAIN_H / gN) * i;
      const tooClose = levels.some(({ price: lp }) => Math.abs(mapY(lp, pMin, pMax, MAIN_TOP, MAIN_H) - y) < 10);
      if (!tooClose) {
        ctx.fillStyle = C.text; ctx.font = "9px monospace"; ctx.textAlign = "left";
        ctx.fillText(price.toFixed(3), chartW + 4, y + 3);
      }
    }

    // ── TSI subplot ───────────────────────────────────────────
    if (hasTsi) {
      const TSI_TOP = MAIN_TOP + MAIN_H + 8;
      const TSI_H   = eachSub - 6;
      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, TSI_TOP); ctx.lineTo(chartW, TSI_TOP); ctx.stroke();
      ctx.fillStyle = C.textBrt; ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText("TSI(100) · Pearson r", 4, TSI_TOP + 11);

      for (const { v, label, alpha, dash } of [
        { v:  0.8, label: "+0.8", alpha: "66", dash: [4, 3] },
        { v:  0,   label: "",     alpha: "",   dash: [] },
        { v: -0.8, label: "-0.8", alpha: "66", dash: [4, 3] },
      ] as Array<{ v: number; label: string; alpha: string; dash: number[] }>) {
        const y = mapY(v, -1, 1, TSI_TOP, TSI_H);
        ctx.strokeStyle = v === 0 ? C.axis : (v > 0 ? `#ef4444${alpha}` : `#22c55e${alpha}`);
        ctx.lineWidth = v === 0 ? 1 : 1.2;
        ctx.setLineDash(dash);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
        ctx.setLineDash([]);
        if (label) {
          ctx.fillStyle = v > 0 ? C.bear : C.bull;
          ctx.font = "9px monospace"; ctx.textAlign = "left";
          ctx.fillText(label, chartW + 4, y + 3);
        }
      }
      ctx.strokeStyle = C.tsiLine; ctx.lineWidth = 1.5; ctx.beginPath();
      let firstT = true;
      vTsi.forEach((v, i) => {
        const x = (tsiVisOff + i) * cw + cw / 2;
        const y = mapY(v, -1, 1, TSI_TOP, TSI_H);
        if (firstT) { ctx.moveTo(x, y); firstT = false; } else ctx.lineTo(x, y);
      });
      ctx.stroke();
      const lastTsi = vTsi[vTsi.length - 1] ?? 0;
      ctx.fillStyle = lastTsi < -0.8 ? C.bull : lastTsi > 0.8 ? C.bear : C.tsiLine;
      ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText(lastTsi.toFixed(3), chartW + 4, mapY(lastTsi, -1, 1, TSI_TOP, TSI_H) + 3);
    }

    // ── Momentum subplot ──────────────────────────────────────
    if (hasMom) {
      const MOM_TOP = MAIN_TOP + MAIN_H + 8 + (hasTsi ? eachSub + 4 : 0);
      const MOM_H   = eachSub - 6;
      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, MOM_TOP); ctx.lineTo(chartW, MOM_TOP); ctx.stroke();
      ctx.fillStyle = C.textBrt; ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText("Momentum(55)", 4, MOM_TOP + 11);
      const momAbsMax = Math.max(...vMom.map(Math.abs), 0.0001);
      const mHi =  momAbsMax * 1.1;
      const mLo = -momAbsMax * 1.1;
      const zeroY = mapY(0, mLo, mHi, MOM_TOP, MOM_H);
      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, zeroY); ctx.lineTo(chartW, zeroY); ctx.stroke();
      vMom.forEach((v, i) => {
        const x    = (momVisOff + i) * cw + (cw - bw) / 2;
        const barY = v >= 0 ? mapY(v, mLo, mHi, MOM_TOP, MOM_H) : zeroY;
        const barH = Math.max(Math.abs(mapY(v, mLo, mHi, MOM_TOP, MOM_H) - zeroY), 1);
        let fillColor: string;
        if (trend === "UPTREND")        fillColor = v < 0 ? C.bull + "55" : C.bear + "33";
        else if (trend === "DOWNTREND") fillColor = v > 0 ? C.bear + "55" : C.bull + "33";
        else                            fillColor = (v >= 0 ? C.bull : C.bear) + "44";
        ctx.fillStyle = fillColor;
        ctx.fillRect(x, v >= 0 ? barY : zeroY, Math.max(bw, 1), barH);
      });
      ctx.strokeStyle = C.momLine; ctx.lineWidth = 1.5; ctx.beginPath();
      let firstM = true;
      vMom.forEach((v, i) => {
        const x = (momVisOff + i) * cw + cw / 2;
        const y = mapY(v, mLo, mHi, MOM_TOP, MOM_H);
        if (firstM) { ctx.moveTo(x, y); firstM = false; } else ctx.lineTo(x, y);
      });
      ctx.stroke();
      const lastMom = vMom[vMom.length - 1] ?? 0;
      const lastY   = mapY(lastMom, mLo, mHi, MOM_TOP, MOM_H);
      ctx.fillStyle = (trend === "UPTREND" && lastMom < 0) || (trend === "DOWNTREND" && lastMom > 0) ? C.bull : C.momLine;
      ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText((lastMom >= 0 ? "+" : "") + lastMom.toFixed(4), chartW + 4, lastY + 3);
    }

    // ── Time axis ─────────────────────────────────────────────
    const interval = Math.max(1, Math.floor(n / 7));
    const timeY    = H - SCROLL_H - 4;
    ctx.fillStyle = C.text; ctx.font = "9px monospace"; ctx.textAlign = "center";
    visible.forEach((c, i) => {
      if (i % interval !== 0) return;
      const x = i * cw + cw / 2;
      const d = new Date(c.time * 1000);
      ctx.fillText(d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), x, timeY);
    });

    // ── Scrollbar ─────────────────────────────────────────────
    if (total > VISIBLE) {
      const { BAR_Y, BAR_W, thumbW, thumbX } = getScrollbarGeom(W, H, n, total, clampedOff, maxOff);

      // Track
      ctx.fillStyle = C.scrollBg;
      ctx.beginPath(); ctx.roundRect(2, BAR_Y, BAR_W, SCROLL_H - 3, 4); ctx.fill();

      // Thumb — highlight if dragging scrollbar
      ctx.fillStyle = dragMode.current === "scrollbar" ? "rgba(255,255,255,0.5)" : C.scrollFg;
      ctx.beginPath(); ctx.roundRect(thumbX, BAR_Y, thumbW, SCROLL_H - 3, 4); ctx.fill();

      // Position label
      ctx.fillStyle = clampedOff === 0 ? "#22c55e" : C.textBrt;
      ctx.font = "bold 8px monospace"; ctx.textAlign = "right";
      ctx.fillText(
        clampedOff === 0 ? "LIVE ▶" : `◀ ${clampedOff} bars back`,
        chartW - 4, BAR_Y - 3,
      );
    }
  }, [visible, n, clampedOff, total, maxOff,
      sphLevel, splLevel, cocLevel, trend,
      vTsi, vMom, hasTsi, hasMom, tsiVisOff, momVisOff,
      hoverIdx, getLayout, getScrollbarGeom]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const obs = new ResizeObserver(() => draw());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [draw]);

  // ── Shared: move scroll from an X delta in pixels ──────────
  const applyXDelta = (dx: number) => {
    const cont = containerRef.current;
    if (!cont) return;
    const nn     = nRef.current;
    const chartW = cont.clientWidth - RIGHT;
    const cwLocal = chartW / Math.max(nn, 1);
    const candleDx = Math.round(-dx / cwLocal);
    setScrollOffset(Math.min(Math.max(dragStartOff.current + candleDx, 0), maxOffRef.current));
  };

  // ── Shared: move scroll from scrollbar X position ──────────
  const applyScrollbarX = (clientX: number) => {
    const cont = containerRef.current;
    if (!cont) return;
    const rect  = cont.getBoundingClientRect();
    const W     = cont.clientWidth;
    const H     = cont.clientHeight;
    const tot   = totalRef.current;
    const mo    = maxOffRef.current;
    const nn    = nRef.current;
    const { BAR_W, thumbW } = getScrollbarGeom(W, H, nn, tot, scrollOffRef.current, mo);
    const localX  = clientX - rect.left;
    const trackX  = localX - 2 - thumbW / 2;
    const ratio   = Math.min(Math.max(trackX / (BAR_W - thumbW), 0), 1);
    const newOff  = Math.round((1 - ratio) * mo);
    setScrollOffset(Math.min(Math.max(newOff, 0), mo));
  };

  // ── Mouse wheel ───────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaX !== 0 ? Math.round(e.deltaX / 4) : Math.round(e.deltaY / 4);
      const step  = delta || (e.deltaY > 0 ? 3 : -3);
      setScrollOffset(prev => Math.min(Math.max(prev + step, 0), maxOffRef.current));
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  // ── Mouse down ────────────────────────────────────────────
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const cont = containerRef.current;
    if (!cont) return;
    const rect = cont.getBoundingClientRect();
    const H    = cont.clientHeight;

    if (isOnScrollbar(e.clientY, rect, H) && totalRef.current > VISIBLE) {
      dragMode.current = "scrollbar";
      dragStartOff.current = scrollOffRef.current;
      applyScrollbarX(e.clientX);
    } else {
      dragMode.current   = "chart";
      dragStartX.current = e.clientX;
      dragStartOff.current = scrollOffRef.current;
      setHoverIdx(null);
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const cont = containerRef.current;
    if (!cont) return;

    if (dragMode.current === "scrollbar") {
      applyScrollbarX(e.clientX);
      return;
    }
    if (dragMode.current === "chart") {
      applyXDelta(e.clientX - dragStartX.current);
      return;
    }
    // Hover crosshair
    const nn      = nRef.current;
    const chartW  = cont.clientWidth - RIGHT;
    const cwLocal = chartW / Math.max(nn, 1);
    const rect    = e.currentTarget.getBoundingClientRect();
    const mouseX  = e.clientX - rect.left;
    const idx     = Math.floor(mouseX / cwLocal);
    if (idx >= 0 && idx < nn) setHoverIdx(idx);
  };

  const handleMouseUp = () => { dragMode.current = "none"; };

  // ── Touch events (mobile) ─────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    const cont   = containerRef.current;
    if (!canvas || !cont) return;

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      const touch = e.touches[0];
      const rect  = cont.getBoundingClientRect();
      const H     = cont.clientHeight;

      if (isOnScrollbar(touch.clientY, rect, H) && totalRef.current > VISIBLE) {
        e.preventDefault();
        dragMode.current     = "scrollbar";
        dragStartOff.current = scrollOffRef.current;
        applyScrollbarX(touch.clientX);
      } else {
        // Don't preventDefault for chart area — allow page scroll if needed
        dragMode.current     = "chart";
        dragStartX.current   = touch.clientX;
        dragStartOff.current = scrollOffRef.current;
      }
    };

    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      if (dragMode.current === "none") return;
      e.preventDefault(); // prevent page scroll while panning chart
      const touch = e.touches[0];
      if (dragMode.current === "scrollbar") {
        applyScrollbarX(touch.clientX);
      } else {
        applyXDelta(touch.clientX - dragStartX.current);
      }
    };

    const onTouchEnd = () => { dragMode.current = "none"; };

    canvas.addEventListener("touchstart", onTouchStart, { passive: false });
    canvas.addEventListener("touchmove",  onTouchMove,  { passive: false });
    canvas.addEventListener("touchend",   onTouchEnd);
    return () => {
      canvas.removeEventListener("touchstart", onTouchStart);
      canvas.removeEventListener("touchmove",  onTouchMove);
      canvas.removeEventListener("touchend",   onTouchEnd);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOnScrollbar, getScrollbarGeom]);

  const hoverCandle = hoverIdx !== null ? visible[hoverIdx] : null;

  return (
    <div ref={containerRef} className="relative w-full select-none" style={{ height: 660 }}>
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ cursor: dragMode.current === "scrollbar" ? "ew-resize" : dragMode.current === "chart" ? "grabbing" : "crosshair" }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => { dragMode.current = "none"; setHoverIdx(null); }}
      />
      {hoverCandle && (
        <div className="absolute top-3 left-3 bg-[#0f172a] border border-[#1e293b] rounded px-3 py-2 text-xs font-mono pointer-events-none z-10 shadow-xl">
          <div className="text-[#6b7280] mb-1.5 text-[10px]">
            {new Date(hoverCandle.time * 1000).toLocaleString([], {
              month: "short", day: "numeric",
              hour: "2-digit", minute: "2-digit",
            })}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            <span className="text-[#6b7280]">O</span>
            <span className="tabular-nums text-right">{hoverCandle.open.toFixed(4)}</span>
            <span className="text-green-400">H</span>
            <span className="tabular-nums text-right">{hoverCandle.high.toFixed(4)}</span>
            <span className="text-red-400">L</span>
            <span className="tabular-nums text-right">{hoverCandle.low.toFixed(4)}</span>
            <span className={hoverCandle.close >= hoverCandle.open ? "text-green-400" : "text-red-400"}>C</span>
            <span className="tabular-nums text-right font-bold">{hoverCandle.close.toFixed(4)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
