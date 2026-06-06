import { useRef, useEffect, useState, useCallback } from "react";
import type { Candle } from "@workspace/api-client-react";

interface CandleChartProps {
  candles: Candle[];
  tsiValues?: number[];
  macdValues?: number[];
  macdSignalValues?: number[];
  macdHistValues?: number[];
  supportLevels?: number[];
  resistanceLevels?: number[];
}

const C = {
  bg: "#0d1117",
  panel: "#111827",
  grid: "rgba(255,255,255,0.04)",
  axis: "rgba(255,255,255,0.12)",
  text: "#6b7280",
  textBright: "#9ca3af",
  bull: "#22c55e",
  bear: "#ef4444",
  tsiLine: "#00d4ff",
  macdLine: "#00d4ff",
  sigLine: "#f59e0b",
  support: "#22c55e",
  resistance: "#ef4444",
  crosshair: "rgba(255,255,255,0.15)",
};

const VISIBLE = 200;
const RIGHT = 72;
const BOTTOM = 20;

export function CandleChart({
  candles,
  tsiValues = [],
  macdValues = [],
  macdSignalValues = [],
  macdHistValues = [],
  supportLevels = [],
  resistanceLevels = [],
}: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const visible = candles.slice(-VISIBLE);
  const vTsi = tsiValues.slice(-VISIBLE);
  const vMacdHist = macdHistValues.slice(-VISIBLE);
  const vMacd = macdValues.slice(-VISIBLE);
  const vSig = macdSignalValues.slice(-VISIBLE);

  const hasTsi = vTsi.length > 0;
  const hasMacd = vMacdHist.length > 0;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || visible.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const W = container.clientWidth;
    const H = container.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";

    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);

    // ─── Layout ──────────────────────────────────────────────
    const subH = hasTsi && hasMacd ? 130 : hasTsi || hasMacd ? 130 : 0;
    const subCount = (hasTsi ? 1 : 0) + (hasMacd ? 1 : 0);
    const eachSubH = subCount > 0 ? (subH / subCount) : 0;

    const MAIN_TOP = 8;
    const MAIN_H = H - BOTTOM - 8 - subH - (subCount > 0 ? 8 : 0);
    const chartW = W - RIGHT;
    const n = visible.length;
    const cw = chartW / n;
    const bw = Math.max(cw * 0.65, 1);

    const mapY = (v: number, lo: number, hi: number, top: number, h: number) => {
      if (hi === lo) return top + h / 2;
      return top + ((hi - v) / (hi - lo)) * h;
    };

    // ─── Clear ───────────────────────────────────────────────
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    // ─── Price range ─────────────────────────────────────────
    const highs = visible.map(c => c.high);
    const lows  = visible.map(c => c.low);
    const pMax0 = Math.max(...highs);
    const pMin0 = Math.min(...lows);
    const pad = (pMax0 - pMin0) * 0.06;
    const pMax = pMax0 + pad;
    const pMin = pMin0 - pad;

    // ─── Grid ────────────────────────────────────────────────
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    const gridN = 6;
    for (let i = 0; i <= gridN; i++) {
      const y = MAIN_TOP + (MAIN_H / gridN) * i;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(chartW, y);
      ctx.stroke();
    }

    // ─── Fractal levels ──────────────────────────────────────
    const drawLevel = (price: number, color: string, label: string) => {
      const y = mapY(price, pMin, pMax, MAIN_TOP, MAIN_H);
      if (y < MAIN_TOP - 2 || y > MAIN_TOP + MAIN_H + 2) return;
      ctx.strokeStyle = color + "99";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(chartW, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.font = "9px monospace";
      ctx.textAlign = "left";
      ctx.fillText(label, chartW + 3, y + 3);
    };
    resistanceLevels.forEach(p => drawLevel(p, C.resistance, `R ${p.toFixed(4)}`));
    supportLevels.forEach(p    => drawLevel(p, C.support,    `S ${p.toFixed(4)}`));

    // ─── Candles ─────────────────────────────────────────────
    visible.forEach((c, i) => {
      const isGreen = c.close >= c.open;
      const col = isGreen ? C.bull : C.bear;
      const cx = i * cw + cw / 2;
      const highY = mapY(c.high,  pMin, pMax, MAIN_TOP, MAIN_H);
      const lowY  = mapY(c.low,   pMin, pMax, MAIN_TOP, MAIN_H);
      const openY = mapY(c.open,  pMin, pMax, MAIN_TOP, MAIN_H);
      const closeY= mapY(c.close, pMin, pMax, MAIN_TOP, MAIN_H);
      // Wick
      ctx.strokeStyle = col;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx, highY);
      ctx.lineTo(cx, lowY);
      ctx.stroke();
      // Body
      const bTop = Math.min(openY, closeY);
      const bH   = Math.max(Math.abs(closeY - openY), 1);
      ctx.fillStyle = isGreen ? col : col;
      ctx.globalAlpha = i === hoverIdx ? 1 : 0.9;
      ctx.fillRect(i * cw + (cw - bw) / 2, bTop, bw, bH);
      ctx.globalAlpha = 1;
    });

    // Hover highlight
    if (hoverIdx !== null && hoverIdx < visible.length) {
      const c = visible[hoverIdx];
      const cx = hoverIdx * cw + cw / 2;
      // Vertical crosshair
      ctx.strokeStyle = C.crosshair;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(cx, MAIN_TOP);
      ctx.lineTo(cx, MAIN_TOP + MAIN_H);
      ctx.stroke();
      ctx.setLineDash([]);
      // Price label
      const closeY = mapY(c.close, pMin, pMax, MAIN_TOP, MAIN_H);
      ctx.fillStyle = c.close >= c.open ? C.bull : C.bear;
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "left";
      ctx.fillText(c.close.toFixed(4), chartW + 3, closeY + 3);
    }

    // ─── Price axis ──────────────────────────────────────────
    ctx.fillStyle = C.text;
    ctx.font = "9px monospace";
    ctx.textAlign = "left";
    for (let i = 0; i <= gridN; i++) {
      const price = pMax - (i / gridN) * (pMax - pMin);
      const y = MAIN_TOP + (MAIN_H / gridN) * i;
      ctx.fillText(price.toFixed(3), chartW + 3, y + 3);
    }

    // ─── TSI subplot ─────────────────────────────────────────
    if (hasTsi) {
      const TSI_TOP = MAIN_TOP + MAIN_H + 8;
      const TSI_H = eachSubH - 4;

      // Separator + label
      ctx.strokeStyle = C.axis;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, TSI_TOP);
      ctx.lineTo(chartW, TSI_TOP);
      ctx.stroke();

      ctx.fillStyle = C.textBright;
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "left";
      ctx.fillText("TSI(55) · Pearson r", 4, TSI_TOP + 11);

      // Background panel
      ctx.fillStyle = C.panel + "66";
      ctx.fillRect(0, TSI_TOP, chartW, TSI_H);

      // Threshold lines
      const drawTsiRef = (level: number, label: string, color: string) => {
        const y = mapY(level, -1, 1, TSI_TOP, TSI_H);
        ctx.strokeStyle = level === 0 ? C.axis : color + "55";
        ctx.lineWidth = 1;
        ctx.setLineDash(level === 0 ? [] : [3, 3]);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(chartW, y);
        ctx.stroke();
        ctx.setLineDash([]);
        if (level !== 0) {
          ctx.fillStyle = color;
          ctx.font = "9px monospace";
          ctx.textAlign = "left";
          ctx.fillText(label, chartW + 3, y + 3);
        }
      };
      drawTsiRef(0.7, "+0.7", C.bear);
      drawTsiRef(0, "0", C.axis);
      drawTsiRef(-0.7, "-0.7", C.bull);

      // TSI line
      const tsiStart = n - vTsi.length;
      ctx.strokeStyle = C.tsiLine;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let firstTsi = true;
      vTsi.forEach((val, i) => {
        const ci = tsiStart + i;
        const x = ci * cw + cw / 2;
        const y = mapY(val, -1, 1, TSI_TOP, TSI_H);
        if (firstTsi) { ctx.moveTo(x, y); firstTsi = false; }
        else ctx.lineTo(x, y);
      });
      ctx.stroke();

      // Fill above/below thresholds
      const lastTsi = vTsi[vTsi.length - 1] ?? 0;
      const lastTsiY = mapY(lastTsi, -1, 1, TSI_TOP, TSI_H);
      ctx.fillStyle = lastTsi < -0.7 ? C.bull : lastTsi > 0.7 ? C.bear : C.tsiLine;
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "left";
      ctx.fillText(lastTsi.toFixed(3), chartW + 3, lastTsiY + 3);
    }

    // ─── MACD subplot ────────────────────────────────────────
    if (hasMacd) {
      const MACD_TOP = MAIN_TOP + MAIN_H + 8 + (hasTsi ? eachSubH + 2 : 0);
      const MACD_H = eachSubH - 4;

      ctx.strokeStyle = C.axis;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, MACD_TOP);
      ctx.lineTo(chartW, MACD_TOP);
      ctx.stroke();

      ctx.fillStyle = C.textBright;
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "left";
      ctx.fillText("MACD(21,55,21)", 4, MACD_TOP + 11);

      ctx.fillStyle = C.panel + "66";
      ctx.fillRect(0, MACD_TOP, chartW, MACD_H);

      const allVals = [...vMacdHist, ...vMacd, ...vSig, 0];
      const mMax = Math.max(...allVals);
      const mMin = Math.min(...allVals);
      const mRange = mMax - mMin || 1;
      const mPad = mRange * 0.1;
      const mHi = mMax + mPad;
      const mLo = mMin - mPad;

      // Zero line
      const zeroY = mapY(0, mLo, mHi, MACD_TOP, MACD_H);
      ctx.strokeStyle = C.axis;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, zeroY);
      ctx.lineTo(chartW, zeroY);
      ctx.stroke();

      const mStart = n - vMacdHist.length;

      // Histogram
      vMacdHist.forEach((val, i) => {
        const ci = mStart + i;
        const x = ci * cw + (cw - bw) / 2;
        const barY = val >= 0 ? mapY(val, mLo, mHi, MACD_TOP, MACD_H) : zeroY;
        const barH = Math.max(Math.abs(mapY(val, mLo, mHi, MACD_TOP, MACD_H) - zeroY), 1);
        ctx.fillStyle = val >= 0 ? C.bull + "99" : C.bear + "99";
        ctx.fillRect(x, val >= 0 ? barY : zeroY, Math.max(bw, 1), barH);
      });

      // MACD line
      const drawIndicatorLine = (vals: number[], color: string, dash: number[]) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.setLineDash(dash);
        ctx.beginPath();
        let first = true;
        vals.forEach((val, i) => {
          const ci = mStart + i;
          const x = ci * cw + cw / 2;
          const y = mapY(val, mLo, mHi, MACD_TOP, MACD_H);
          if (first) { ctx.moveTo(x, y); first = false; }
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.setLineDash([]);
      };

      drawIndicatorLine(vMacd, C.macdLine, []);
      drawIndicatorLine(vSig,  C.sigLine,  [3, 2]);

      // Current value label
      const lastHist = vMacdHist[vMacdHist.length - 1] ?? 0;
      ctx.fillStyle = lastHist >= 0 ? C.bull : C.bear;
      ctx.font = "bold 9px monospace";
      ctx.textAlign = "left";
      ctx.fillText((lastHist >= 0 ? "+" : "") + lastHist.toFixed(5), chartW + 3, zeroY + (lastHist >= 0 ? -4 : 11));
    }

    // ─── Time axis ───────────────────────────────────────────
    const interval = Math.max(1, Math.floor(n / 7));
    ctx.fillStyle = C.text;
    ctx.font = "9px monospace";
    ctx.textAlign = "center";
    visible.forEach((c, i) => {
      if (i % interval === 0) {
        const x = i * cw + cw / 2;
        const d = new Date(c.time * 1000);
        const label = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        ctx.fillText(label, x, H - 4);
      }
    });
  }, [visible, vTsi, vMacd, vSig, vMacdHist, hasTsi, hasMacd, supportLevels, resistanceLevels, hoverIdx]);

  useEffect(() => { draw(); }, [draw]);

  // Redraw on resize
  useEffect(() => {
    const obs = new ResizeObserver(() => draw());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [draw]);

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || visible.length === 0) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const chartW = container.clientWidth - RIGHT;
    const cw = chartW / visible.length;
    const idx = Math.floor(mouseX / cw);
    if (idx >= 0 && idx < visible.length) setHoverIdx(idx);
  };

  const hoverCandle = hoverIdx !== null ? visible[hoverIdx] : null;

  return (
    <div ref={containerRef} className="relative w-full" style={{ height: 600 }}>
      <canvas
        ref={canvasRef}
        className="w-full h-full cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoverIdx(null)}
      />
      {hoverCandle && (
        <div className="absolute top-2 left-2 bg-[#111827] border border-border rounded px-3 py-2 text-xs font-mono pointer-events-none z-10 shadow-lg">
          <div className="text-muted-foreground mb-1.5 text-[10px]">
            {new Date(hoverCandle.time * 1000).toLocaleString([], {
              month: "short", day: "numeric",
              hour: "2-digit", minute: "2-digit",
            })}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
            <span className="text-muted-foreground">O</span>
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
