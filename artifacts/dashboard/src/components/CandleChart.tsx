import { useRef, useEffect, useState, useCallback } from "react";
import type { Candle, FractalMarker } from "@workspace/api-client-react";

interface CandleChartProps {
  candles: Candle[];
  markers?: FractalMarker[];
  hhLevel?: number | null;
  hlLevel?: number | null;
  lhLevel?: number | null;
  llLevel?: number | null;
  trend?: string;
  tsiValues?: number[];
  macdValues?: number[];
  macdSignalValues?: number[];
  macdHistValues?: number[];
}

const MARKER_COLORS: Record<string, string> = {
  HH: "#22c55e",
  HL: "#4ade80",
  LH: "#ef4444",
  LL: "#fca5a5",
};

const LEVEL_STYLE: Record<string, { color: string; dash: number[] }> = {
  HH: { color: "#22c55e", dash: [] },
  HL: { color: "#22c55e", dash: [5, 5] },
  LH: { color: "#ef4444", dash: [] },
  LL: { color: "#ef4444", dash: [5, 5] },
};

const C = {
  bg:      "#0d1117",
  panel:   "#0f172a",
  grid:    "rgba(255,255,255,0.04)",
  axis:    "rgba(255,255,255,0.10)",
  text:    "#6b7280",
  textBrt: "#9ca3af",
  bull:    "#22c55e",
  bear:    "#ef4444",
  tsiLine: "#00d4ff",
  macdLn:  "#00d4ff",
  sigLn:   "#f59e0b",
};

const VISIBLE = 300;
const RIGHT   = 110;  // wide enough for "HH 747.10000"
const BOTTOM  = 22;
const DOT_R   = 4;

function mapY(v: number, lo: number, hi: number, top: number, h: number) {
  if (hi === lo) return top + h / 2;
  return top + ((hi - v) / (hi - lo)) * h;
}

export function CandleChart({
  candles,
  markers = [],
  hhLevel, hlLevel, lhLevel, llLevel,
  tsiValues = [], macdValues = [], macdSignalValues = [], macdHistValues = [],
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const total   = candles.length;
  const start   = Math.max(0, total - VISIBLE);
  const visible = candles.slice(start);
  const n       = visible.length;

  // Align indicator tails to visible candles
  const vTsi       = tsiValues.slice(-n);
  const vMacdHist  = macdHistValues.slice(-n);
  const vMacd      = macdValues.slice(-n);
  const vSig       = macdSignalValues.slice(-n);
  const hasTsi     = vTsi.length > 0;
  const hasMacd    = vMacdHist.length > 0;

  // Which markers fall within the visible window?
  const visibleMarkers = markers.filter(m => m.index >= start && m.index < total);

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

    // ── Layout ─────────────────────────────────────────────
    const subPanelH  = hasTsi && hasMacd ? 240 : (hasTsi || hasMacd ? 120 : 0);
    const eachSub    = subPanelH / Math.max((hasTsi ? 1 : 0) + (hasMacd ? 1 : 0), 1);
    const MAIN_TOP   = 10;
    const MAIN_H     = H - BOTTOM - 10 - subPanelH - (subPanelH > 0 ? 8 : 0);
    const chartW     = W - RIGHT;
    const cw         = chartW / n;
    const bw         = Math.max(cw * 0.6, 1);

    // ── Clear ───────────────────────────────────────────────
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    // ── Price range ─────────────────────────────────────────
    const pMax0 = Math.max(...visible.map(c => c.high));
    const pMin0 = Math.min(...visible.map(c => c.low));
    // Also include level lines in range so they're always visible
    const levelPrices = [hhLevel, hlLevel, lhLevel, llLevel].filter(Boolean) as number[];
    const allPrices   = [pMax0, pMin0, ...levelPrices];
    const rawMax = Math.max(...allPrices);
    const rawMin = Math.min(...allPrices);
    const pad    = (rawMax - rawMin) * 0.06;
    const pMax   = rawMax + pad;
    const pMin   = rawMin - pad;

    // ── Grid ────────────────────────────────────────────────
    ctx.strokeStyle = C.grid;
    ctx.lineWidth   = 1;
    const gN = 6;
    for (let i = 0; i <= gN; i++) {
      const y = MAIN_TOP + (MAIN_H / gN) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
    }

    // ── Horizontal level lines + right-axis labels ──────────
    const levels: Array<{ key: string; price: number }> = [];
    if (hhLevel != null) levels.push({ key: "HH", price: hhLevel });
    if (hlLevel != null) levels.push({ key: "HL", price: hlLevel });
    if (lhLevel != null) levels.push({ key: "LH", price: lhLevel });
    if (llLevel != null) levels.push({ key: "LL", price: llLevel });

    for (const { key, price } of levels) {
      const { color, dash } = LEVEL_STYLE[key];
      const y = mapY(price, pMin, pMax, MAIN_TOP, MAIN_H);
      if (y < MAIN_TOP - 4 || y > MAIN_TOP + MAIN_H + 4) continue;
      ctx.strokeStyle = color + "cc";
      ctx.lineWidth   = 1.5;
      ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
      ctx.setLineDash([]);
      // Label on right
      ctx.fillStyle = color;
      ctx.font      = "bold 10px monospace";
      ctx.textAlign = "left";
      ctx.fillText(`${key}  ${price.toFixed(4)}`, chartW + 4, y + 3);
    }

    // ── Candles ─────────────────────────────────────────────
    for (let i = 0; i < n; i++) {
      const c      = visible[i];
      const isUp   = c.close >= c.open;
      const col    = isUp ? C.bull : C.bear;
      const cx     = i * cw + cw / 2;
      const highY  = mapY(c.high,  pMin, pMax, MAIN_TOP, MAIN_H);
      const lowY   = mapY(c.low,   pMin, pMax, MAIN_TOP, MAIN_H);
      const openY  = mapY(c.open,  pMin, pMax, MAIN_TOP, MAIN_H);
      const closeY = mapY(c.close, pMin, pMax, MAIN_TOP, MAIN_H);

      ctx.strokeStyle   = col;
      ctx.lineWidth     = 1;
      ctx.globalAlpha   = i === hoverIdx ? 1 : 0.88;
      ctx.beginPath(); ctx.moveTo(cx, highY); ctx.lineTo(cx, lowY); ctx.stroke();

      const bTop = Math.min(openY, closeY);
      const bH   = Math.max(Math.abs(closeY - openY), 1);
      ctx.fillStyle = col;
      ctx.fillRect(i * cw + (cw - bw) / 2, bTop, bw, bH);
      ctx.globalAlpha = 1;
    }

    // ── Fractal marker dots ──────────────────────────────────
    for (const m of visibleMarkers) {
      const ci  = m.index - start;           // position in visible array
      const c   = visible[ci];
      if (!c) continue;
      const cx  = ci * cw + cw / 2;
      const col = MARKER_COLORS[m.type] ?? "#ffffff";
      const isHigh = m.type === "HH" || m.type === "LH";
      const dotY   = isHigh
        ? mapY(c.high,  pMin, pMax, MAIN_TOP, MAIN_H) - DOT_R * 2.5
        : mapY(c.low,   pMin, pMax, MAIN_TOP, MAIN_H) + DOT_R * 2.5;

      // Filled dot
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(cx, dotY, DOT_R, 0, Math.PI * 2);
      ctx.fill();

      // Tiny label next to dot (only if candles are wide enough)
      if (cw > 6) {
        ctx.fillStyle = col;
        ctx.font      = "bold 8px monospace";
        ctx.textAlign = "center";
        ctx.fillText(m.type, cx, isHigh ? dotY - DOT_R - 2 : dotY + DOT_R + 9);
      }
    }

    // ── Crosshair & price label on hover ────────────────────
    if (hoverIdx !== null && hoverIdx < n) {
      const c  = visible[hoverIdx];
      const cx = hoverIdx * cw + cw / 2;
      ctx.strokeStyle = "rgba(255,255,255,0.18)";
      ctx.lineWidth   = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(cx, MAIN_TOP); ctx.lineTo(cx, MAIN_TOP + MAIN_H); ctx.stroke();
      ctx.setLineDash([]);
      const closeY = mapY(c.close, pMin, pMax, MAIN_TOP, MAIN_H);
      ctx.fillStyle = c.close >= c.open ? C.bull : C.bear;
      ctx.font      = "bold 10px monospace";
      ctx.textAlign = "left";
      ctx.fillText(c.close.toFixed(4), chartW + 4, closeY + 3);
    }

    // ── Price axis ──────────────────────────────────────────
    ctx.fillStyle = C.text;
    ctx.font      = "9px monospace";
    ctx.textAlign = "left";
    for (let i = 0; i <= gN; i++) {
      const price = pMax - (i / gN) * (pMax - pMin);
      const y     = MAIN_TOP + (MAIN_H / gN) * i;
      // Skip if a level label is too close
      const tooClose = levels.some(({ price: lp }) => {
        const ly = mapY(lp, pMin, pMax, MAIN_TOP, MAIN_H);
        return Math.abs(ly - y) < 10;
      });
      if (!tooClose) {
        ctx.fillStyle = C.text;
        ctx.fillText(price.toFixed(3), chartW + 4, y + 3);
      }
    }

    // ── TSI subplot ─────────────────────────────────────────
    if (hasTsi) {
      const TSI_TOP = MAIN_TOP + MAIN_H + 8;
      const TSI_H   = eachSub - 6;

      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, TSI_TOP); ctx.lineTo(chartW, TSI_TOP); ctx.stroke();
      ctx.fillStyle = C.textBrt; ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText("TSI(55) · Pearson r", 4, TSI_TOP + 11);

      // Threshold lines: ±0.7 = trade entry (brighter), ±0.6 = validity window (dimmer)
      const thresholds: Array<{ v: number; label: string; alpha: string; dash: number[] }> = [
        { v:  0.7, label: "+0.7", alpha: "55", dash: [4, 3] },
        { v:  0.6, label: "+0.6", alpha: "30", dash: [2, 4] },
        { v:  0,   label: "",     alpha: "",   dash: [] },
        { v: -0.6, label: "-0.6", alpha: "30", dash: [2, 4] },
        { v: -0.7, label: "-0.7", alpha: "55", dash: [4, 3] },
      ];
      for (const { v, label, alpha, dash } of thresholds) {
        const y = mapY(v, -1, 1, TSI_TOP, TSI_H);
        ctx.strokeStyle = v === 0 ? C.axis : (v > 0 ? `#ef4444${alpha}` : `#22c55e${alpha}`);
        ctx.lineWidth   = v === 0 ? 1 : (Math.abs(v) === 0.7 ? 1.2 : 0.8);
        ctx.setLineDash(dash);
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(chartW, y); ctx.stroke();
        ctx.setLineDash([]);
        if (label) {
          ctx.fillStyle = v > 0 ? C.bear : C.bull;
          ctx.font      = "9px monospace"; ctx.textAlign = "left";
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
      ctx.fillStyle = lastTsi < -0.7 ? C.bull : lastTsi > 0.7 ? C.bear : C.tsiLine;
      ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText(lastTsi.toFixed(3), chartW + 4, mapY(lastTsi, -1, 1, TSI_TOP, TSI_H) + 3);
    }

    // ── MACD subplot ─────────────────────────────────────────
    if (hasMacd) {
      const MACD_TOP = MAIN_TOP + MAIN_H + 8 + (hasTsi ? eachSub + 4 : 0);
      const MACD_H   = eachSub - 6;

      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, MACD_TOP); ctx.lineTo(chartW, MACD_TOP); ctx.stroke();
      ctx.fillStyle = C.textBrt; ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText("MACD(21,55,21)", 4, MACD_TOP + 11);

      const allVals = [...vMacdHist, ...vMacd, ...vSig, 0];
      const mHi0    = Math.max(...allVals);
      const mLo0    = Math.min(...allVals);
      const mPad    = (mHi0 - mLo0) * 0.1;
      const mHi     = mHi0 + mPad;
      const mLo     = mLo0 - mPad;
      const zeroY   = mapY(0, mLo, mHi, MACD_TOP, MACD_H);

      ctx.strokeStyle = C.axis; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, zeroY); ctx.lineTo(chartW, zeroY); ctx.stroke();

      const mStart = n - vMacdHist.length;

      // Histogram
      vMacdHist.forEach((v, i) => {
        const x    = (mStart + i) * cw + (cw - bw) / 2;
        const barY = v >= 0 ? mapY(v, mLo, mHi, MACD_TOP, MACD_H) : zeroY;
        const barH = Math.max(Math.abs(mapY(v, mLo, mHi, MACD_TOP, MACD_H) - zeroY), 1);
        ctx.fillStyle = v >= 0 ? C.bull + "99" : C.bear + "99";
        ctx.fillRect(x, v >= 0 ? barY : zeroY, Math.max(bw, 1), barH);
      });

      // Lines
      const drawLine = (vals: number[], color: string, dash: number[]) => {
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.setLineDash(dash);
        ctx.beginPath();
        let first = true;
        vals.forEach((v, i) => {
          const x = (mStart + i) * cw + cw / 2;
          const y = mapY(v, mLo, mHi, MACD_TOP, MACD_H);
          if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y);
        });
        ctx.stroke(); ctx.setLineDash([]);
      };
      drawLine(vMacd, C.macdLn, []);
      drawLine(vSig,  C.sigLn,  [3, 2]);

      const lastH = vMacdHist[vMacdHist.length - 1] ?? 0;
      ctx.fillStyle = lastH >= 0 ? C.bull : C.bear;
      ctx.font = "bold 9px monospace"; ctx.textAlign = "left";
      ctx.fillText((lastH >= 0 ? "+" : "") + lastH.toFixed(5), chartW + 4,
        zeroY + (lastH >= 0 ? -4 : 12));
    }

    // ── Time axis ────────────────────────────────────────────
    const interval = Math.max(1, Math.floor(n / 7));
    ctx.fillStyle  = C.text; ctx.font = "9px monospace"; ctx.textAlign = "center";
    visible.forEach((c, i) => {
      if (i % interval !== 0) return;
      const x = i * cw + cw / 2;
      const d = new Date(c.time * 1000);
      ctx.fillText(d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), x, H - 4);
    });
  }, [visible, n, start, visibleMarkers, hhLevel, hlLevel, lhLevel, llLevel,
      vTsi, vMacd, vSig, vMacdHist, hasTsi, hasMacd, hoverIdx]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const obs = new ResizeObserver(() => draw());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [draw]);

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const cont = containerRef.current;
    if (!cont || n === 0) return;
    const rect  = e.currentTarget.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const cw    = (cont.clientWidth - RIGHT) / n;
    const idx   = Math.floor(mouseX / cw);
    if (idx >= 0 && idx < n) setHoverIdx(idx);
  };

  const hoverCandle = hoverIdx !== null ? visible[hoverIdx] : null;

  return (
    <div ref={containerRef} className="relative w-full" style={{ height: 660 }}>
      <canvas
        ref={canvasRef}
        className="w-full h-full cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
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
