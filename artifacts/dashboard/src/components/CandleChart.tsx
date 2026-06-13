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
  scrollBg: "rgba(255,255,255,0.06)",
  scrollFg: "rgba(255,255,255,0.18)",
};

const VISIBLE = 300;
const RIGHT   = 120;
const BOTTOM  = 38; // extra room for scroll bar

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
  const [hoverIdx, setHoverIdx]       = useState<number | null>(null);
  // scrollOffset: how many candles from the right end are hidden (0 = latest candles visible)
  const [scrollOffset, setScrollOffset] = useState(0);
  const isDragging   = useRef(false);
  const dragStartX   = useRef(0);
  const dragStartOff = useRef(0);

  const total   = candles.length;
  const maxOff  = Math.max(0, total - VISIBLE);
  const clampedOff = Math.min(Math.max(scrollOffset, 0), maxOff);
  const start   = Math.max(0, total - VISIBLE - clampedOff);
  const visible = candles.slice(start, start + VISIBLE);
  const n       = visible.length;

  const vTsi = tsiValues.slice(start, start + VISIBLE);
  const vMom = momentumValues.slice(start, start + VISIBLE);
  const hasTsi = vTsi.length > 0;
  const hasMom = vMom.length > 0;

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

    const SCROLL_H   = 12;
    const subCount   = (hasTsi ? 1 : 0) + (hasMom ? 1 : 0);
    const subPanelH  = subCount === 2 ? 240 : subCount === 1 ? 120 : 0;
    const eachSub    = subPanelH / Math.max(subCount, 1);
    const MAIN_TOP   = 10;
    const MAIN_H     = H - BOTTOM - 10 - subPanelH - (subPanelH > 0 ? 8 : 0) - SCROLL_H;
    const chartW     = W - RIGHT;
    const cw         = chartW / n;
    const bw         = Math.max(cw * 0.6, 1);

    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

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

    const pMax0  = Math.max(...visible.map(c => c.high));
    const pMin0  = Math.min(...visible.map(c => c.low));
    const lvPrices = levels.map(l => l.price);
    const rawMax = Math.max(pMax0, ...lvPrices);
    const rawMin = Math.min(pMin0, ...lvPrices);
    const pad    = (rawMax - rawMin) * 0.06;
    const pMax   = rawMax + pad;
    const pMin   = rawMin - pad;

    ctx.strokeStyle = C.grid; ctx.lineWidth = 1;
    const gN = 6;
    for (let i = 0; i <= gN; i++) {
      const y = MAIN_TOP + (MAIN_H / gN) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
    }

    for (const { label, price, color, dash } of levels) {
      const y = mapY(price, pMin, pMax, MAIN_TOP, MAIN_H);
      if (y < MAIN_TOP - 4 || y > MAIN_TOP + MAIN_H + 4) continue;
      ctx.strokeStyle = color + "cc";
      ctx.lineWidth   = label === "CoC" ? 1.2 : 1.8;
      ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font      = "bold 10px monospace";
      ctx.textAlign = "left";
      ctx.fillText(`${label}  ${price.toFixed(4)}`, chartW + 4, y + 3);
    }

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

      const bTop = Math.min(openY, closeY);
      const bH   = Math.max(Math.abs(closeY - openY), 1);
      ctx.fillStyle = col;
      ctx.fillRect(i * cw + (cw - bw) / 2, bTop, bw, bH);
      ctx.globalAlpha = 1;
    }

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

    ctx.fillStyle = C.text; ctx.font = "9px monospace"; ctx.textAlign = "left";
    for (let i = 0; i <= gN; i++) {
      const price = pMax - (i / gN) * (pMax - pMin);
      const y     = MAIN_TOP + (MAIN_H / gN) * i;
      const tooClose = levels.some(({ price: lp }) => {
        const ly = mapY(lp, pMin, pMax, MAIN_TOP, MAIN_H);
        return Math.abs(ly - y) < 10;
      });
      if (!tooClose) {
        ctx.fillStyle = C.text;
        ctx.fillText(price.toFixed(3), chartW + 4, y + 3);
      }
    }

    if (hasTsi) {
      const TSI_TOP = MAIN_TOP + MAIN_H + 8;
      const TSI_H   = eachSub - 6;

      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, TSI_TOP); ctx.lineTo(chartW, TSI_TOP); ctx.stroke();
      ctx.fillStyle = C.textBrt; ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText("TSI(100) · Pearson r", 4, TSI_TOP + 11);

      const thresholds: Array<{ v: number; label: string; alpha: string; dash: number[] }> = [
        { v:  0.8, label: "+0.8", alpha: "66", dash: [4, 3] },
        { v:  0,   label: "",     alpha: "",   dash: [] },
        { v: -0.8, label: "-0.8", alpha: "66", dash: [4, 3] },
      ];
      for (const { v, label, alpha, dash } of thresholds) {
        const y = mapY(v, -1, 1, TSI_TOP, TSI_H);
        ctx.strokeStyle = v === 0 ? C.axis : (v > 0 ? `#ef4444${alpha}` : `#22c55e${alpha}`);
        ctx.lineWidth   = v === 0 ? 1 : 1.2;
        ctx.setLineDash(dash);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
        ctx.setLineDash([]);
        if (label) {
          ctx.fillStyle = v > 0 ? C.bear : C.bull;
          ctx.font = "9px monospace"; ctx.textAlign = "left";
          ctx.fillText(label, chartW + 4, y + 3);
        }
      }

      const tsiStart = n - vTsi.length;
      ctx.strokeStyle = C.tsiLine; ctx.lineWidth = 1.5;
      ctx.beginPath();
      let firstT = true;
      vTsi.forEach((v, i) => {
        const x = (tsiStart + i) * cw + cw / 2;
        const y = mapY(v, -1, 1, TSI_TOP, TSI_H);
        if (firstT) { ctx.moveTo(x, y); firstT = false; } else ctx.lineTo(x, y);
      });
      ctx.stroke();

      const lastTsi = vTsi[vTsi.length - 1] ?? 0;
      ctx.fillStyle = lastTsi < -0.8 ? C.bull : lastTsi > 0.8 ? C.bear : C.tsiLine;
      ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText(lastTsi.toFixed(3), chartW + 4, mapY(lastTsi, -1, 1, TSI_TOP, TSI_H) + 3);
    }

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

      const momStart = n - vMom.length;
      vMom.forEach((v, i) => {
        const x   = (momStart + i) * cw + (cw - bw) / 2;
        const barY = v >= 0 ? mapY(v, mLo, mHi, MOM_TOP, MOM_H) : zeroY;
        const barH = Math.max(Math.abs(mapY(v, mLo, mHi, MOM_TOP, MOM_H) - zeroY), 1);
        let fillColor: string;
        if (trend === "UPTREND") {
          fillColor = v < 0 ? C.bull + "55" : C.bear + "33";
        } else if (trend === "DOWNTREND") {
          fillColor = v > 0 ? C.bear + "55" : C.bull + "33";
        } else {
          fillColor = (v >= 0 ? C.bull : C.bear) + "44";
        }
        ctx.fillStyle = fillColor;
        ctx.fillRect(x, v >= 0 ? barY : zeroY, Math.max(bw, 1), barH);
      });

      ctx.strokeStyle = C.momLine; ctx.lineWidth = 1.5;
      ctx.beginPath();
      let firstM = true;
      vMom.forEach((v, i) => {
        const x = (momStart + i) * cw + cw / 2;
        const y = mapY(v, mLo, mHi, MOM_TOP, MOM_H);
        if (firstM) { ctx.moveTo(x, y); firstM = false; } else ctx.lineTo(x, y);
      });
      ctx.stroke();

      const lastMom = vMom[vMom.length - 1] ?? 0;
      const lastY   = mapY(lastMom, mLo, mHi, MOM_TOP, MOM_H);
      let labelColor = C.momLine;
      if (trend === "UPTREND"   && lastMom < 0) labelColor = C.bull;
      if (trend === "DOWNTREND" && lastMom > 0) labelColor = C.bear;
      ctx.fillStyle = labelColor;
      ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText((lastMom >= 0 ? "+" : "") + lastMom.toFixed(4), chartW + 4, lastY + 3);
    }

    // ── Time axis ──────────────────────────────────────────────
    const interval = Math.max(1, Math.floor(n / 7));
    ctx.fillStyle = C.text; ctx.font = "9px monospace"; ctx.textAlign = "center";
    visible.forEach((c, i) => {
      if (i % interval !== 0) return;
      const x = i * cw + cw / 2;
      const d = new Date(c.time * 1000);
      ctx.fillText(d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), x, H - SCROLL_H - 10);
    });

    // ── Scroll bar ─────────────────────────────────────────────
    if (total > VISIBLE) {
      const BAR_Y = H - SCROLL_H - 2;
      const BAR_W = chartW - 4;

      // Track
      ctx.fillStyle = C.scrollBg;
      ctx.beginPath();
      (ctx as any).roundRect?.(2, BAR_Y, BAR_W, SCROLL_H - 2, 4) ??
        ctx.rect(2, BAR_Y, BAR_W, SCROLL_H - 2);
      ctx.fill();

      // Thumb: fraction of total that is visible
      const thumbW  = Math.max((VISIBLE / total) * BAR_W, 20);
      // position: clampedOff=0 → thumb at right, clampedOff=maxOff → thumb at left
      const thumbX  = 2 + (1 - clampedOff / maxOff) * (BAR_W - thumbW);
      ctx.fillStyle = C.scrollFg;
      ctx.beginPath();
      (ctx as any).roundRect?.(thumbX, BAR_Y, thumbW, SCROLL_H - 2, 4) ??
        ctx.rect(thumbX, BAR_Y, thumbW, SCROLL_H - 2);
      ctx.fill();

      // Label
      ctx.fillStyle = C.text; ctx.font = "8px monospace"; ctx.textAlign = "right";
      ctx.fillText(
        clampedOff === 0
          ? "LIVE ▶"
          : `◀ ${clampedOff} bars back`,
        chartW - 4, BAR_Y - 2,
      );
    }
  }, [visible, n, clampedOff, total, maxOff, sphLevel, splLevel, cocLevel, trend,
      vTsi, vMom, hasTsi, hasMom, hoverIdx]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const obs = new ResizeObserver(() => draw());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [draw]);

  // ── Wheel to scroll ─────────────────────────────────────────
  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
    const delta = Math.round(e.deltaY / 3) || (e.deltaY > 0 ? 3 : -3);
    setScrollOffset(prev => Math.min(Math.max(prev + delta, 0), maxOff));
  }, [maxOff]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [handleWheel]);

  // ── Drag to pan ─────────────────────────────────────────────
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    isDragging.current   = true;
    dragStartX.current   = e.clientX;
    dragStartOff.current = clampedOff;
    setHoverIdx(null);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const cont = containerRef.current;
    if (!cont || n === 0) return;
    const chartW = cont.clientWidth - RIGHT;
    const cwLocal = chartW / n;

    if (isDragging.current) {
      const dx        = e.clientX - dragStartX.current;
      const candleDx  = Math.round(-dx / cwLocal);
      setScrollOffset(Math.min(Math.max(dragStartOff.current + candleDx, 0), maxOff));
      return;
    }

    const rect   = e.currentTarget.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const idx    = Math.floor(mouseX / cwLocal);
    if (idx >= 0 && idx < n) setHoverIdx(idx);
  };

  const handleMouseUp = () => { isDragging.current = false; };

  const hoverCandle = hoverIdx !== null ? visible[hoverIdx] : null;

  return (
    <div ref={containerRef} className="relative w-full select-none" style={{ height: 660 }}>
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ cursor: isDragging.current ? "grabbing" : "crosshair" }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => { isDragging.current = false; setHoverIdx(null); }}
      />
      {/* Scroll hint — shown only when at latest position */}
      {clampedOff === 0 && total > VISIBLE && (
        <div className="absolute bottom-10 right-32 text-[9px] font-mono text-[#4b5563] pointer-events-none select-none">
          scroll or drag to pan ←
        </div>
      )}
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
