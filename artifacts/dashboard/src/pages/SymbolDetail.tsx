import { useGetSymbolCandles, getGetSymbolCandlesQueryKey, useGetMarketAnalysis } from "@workspace/api-client-react";
import { useParams, useLocation } from "wouter";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from "recharts";
import type { Candle, SymbolAnalysis, FractalLevel, MACDData, TSIData } from "@workspace/api-client-react";

interface CandleBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  bodyLow: number;
  bodyHigh: number;
  isGreen: boolean;
}

function formatTime(unix: number) {
  return new Date(unix * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDate(unix: number) {
  return new Date(unix * 1000).toLocaleDateString([], { month: "short", day: "numeric" });
}

interface CustomCandleProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: CandleBar;
  index?: number;
}

function CustomCandleShape(props: CustomCandleProps) {
  const { x = 0, y = 0, width = 0, payload } = props;
  if (!payload) return null;

  const { open, high, low, close, isGreen } = payload;
  const stroke = isGreen ? "#22c55e" : "#ef4444";
  const fill = isGreen ? "#22c55e" : "#ef4444";

  const priceRange = high - low;
  if (priceRange === 0) return null;

  const chartHeight = 200;
  const allPrices = [open, high, low, close];
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);

  const scaleY = (price: number, chartMin: number, chartMax: number) => {
    const range = chartMax - chartMin;
    if (range === 0) return y + chartHeight / 2;
    return y + ((chartMax - price) / range) * chartHeight;
  };

  const cx = x + width / 2;
  const bodyTop = scaleY(Math.max(open, close), minP, maxP);
  const bodyBot = scaleY(Math.min(open, close), minP, maxP);
  const wickTop = scaleY(high, minP, maxP);
  const wickBot = scaleY(low, minP, maxP);
  const bodyH = Math.max(bodyBot - bodyTop, 1);

  return (
    <g>
      <line x1={cx} x2={cx} y1={wickTop} y2={wickBot} stroke={stroke} strokeWidth={1} />
      <rect x={x + 1} y={bodyTop} width={Math.max(width - 2, 1)} height={bodyH} fill={fill} opacity={0.9} />
    </g>
  );
}

function StatBadge({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-card border border-border rounded px-3 py-2">
      <div className="text-xs text-muted-foreground font-mono uppercase">{label}</div>
      <div className={`text-sm font-bold font-mono mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}

export default function SymbolDetail() {
  const { symbol } = useParams<{ symbol: string }>();
  const [, setLocation] = useLocation();

  const { data: candles, isLoading: candlesLoading } = useGetSymbolCandles(symbol!, {
    query: { enabled: !!symbol, queryKey: getGetSymbolCandlesQueryKey(symbol!) },
  });

  const { data: marketData } = useGetMarketAnalysis();
  const symData: SymbolAnalysis | undefined = marketData?.symbols.find(
    (s: SymbolAnalysis) => s.symbol === symbol
  );

  const chartData: CandleBar[] = (candles ?? []).map((c: Candle) => ({
    ...c,
    bodyLow: Math.min(c.open, c.close),
    bodyHigh: Math.max(c.open, c.close),
    isGreen: c.close >= c.open,
  }));

  const macd: MACDData | undefined = symData?.macd;
  const tsi: TSIData | undefined = symData?.tsi;
  const fractals: FractalLevel[] = symData?.last_fractals ?? [];
  const supportLevels = fractals.filter((f) => f.type === "SUPPORT");
  const resistanceLevels = fractals.filter((f) => f.type === "RESISTANCE");

  const tsiChartData = (tsi?.values ?? []).map((v, i) => ({ i, value: v }));
  const macdChartData = (macd?.histogram_values ?? []).map((h, i) => ({
    i,
    histogram: h,
    macd: macd?.values?.[i] ?? 0,
    signal: macd?.signal_values?.[i] ?? 0,
  }));

  const stateColors: Record<string, string> = {
    PULLBACK: "text-amber-400",
    BOS_CONTINUATION: "text-cyan-400",
    CHoCH_REVERSAL: "text-purple-400",
    IN_TREND: symData?.trend === "UPTREND" ? "text-green-400" : "text-red-400",
    CONSOLIDATION: "text-gray-400",
  };

  const stateColor = symData ? (stateColors[symData.state] ?? "text-foreground") : "text-foreground";

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border px-6 py-4 flex items-center gap-4">
        <button
          className="text-xs font-mono text-muted-foreground hover:text-primary transition-colors px-2 py-1 border border-border rounded"
          onClick={() => setLocation("/")}
          data-testid="button-back"
        >
          ← BACK
        </button>
        <div>
          <h1 className="text-xl font-bold font-mono text-primary">{symbol}</h1>
          <p className="text-xs text-muted-foreground font-mono">{symData?.name ?? ""}</p>
        </div>
        {symData && (
          <div className="ml-auto text-right">
            <div className="text-2xl font-mono font-bold tabular-nums">
              {symData.price.toLocaleString(undefined, { minimumFractionDigits: 4 })}
            </div>
            <div className={`text-xs font-mono font-bold ${stateColor}`}>
              {symData.state.replace(/_/g, " ")} · {symData.trend}
            </div>
          </div>
        )}
      </header>

      <main className="px-6 py-5 space-y-6">
        {/* Stats row */}
        {symData && (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            <StatBadge label="Volatility" value={`${symData.volatility.toFixed(1)}%`} color="text-foreground" />
            <StatBadge label="Fractals" value={`${symData.fractal_count}`} color="text-cyan-400" />
            {symData.support && <StatBadge label="Support" value={symData.support.toFixed(4)} color="text-green-400" />}
            {symData.resistance && <StatBadge label="Resistance" value={symData.resistance.toFixed(4)} color="text-red-400" />}
            {tsi && (
              <StatBadge
                label={`TSI(55) · ${tsi.strength}`}
                value={`${tsi.value.toFixed(1)}`}
                color={tsi.strength === "STRONG" ? "text-green-400" : tsi.strength === "MODERATE" ? "text-amber-400" : "text-gray-400"}
              />
            )}
            {macd && (
              <StatBadge
                label="MACD Hist"
                value={`${macd.histogram >= 0 ? "+" : ""}${macd.histogram.toFixed(5)}`}
                color={macd.histogram >= 0 ? "text-green-400" : "text-red-400"}
              />
            )}
          </div>
        )}

        {/* Description */}
        {symData?.description && (
          <div className="rounded border border-border bg-card px-4 py-3 text-sm font-mono text-muted-foreground">
            {symData.description}
          </div>
        )}

        {/* Candlestick chart */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <span className="text-sm font-mono font-semibold">PRICE · 1000 CANDLES (1M)</span>
            {candlesLoading && <span className="text-xs text-muted-foreground font-mono animate-pulse">Loading...</span>}
          </div>
          <div className="p-4">
            {candlesLoading ? (
              <Skeleton className="h-52 w-full" />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={chartData.slice(-200)} margin={{ top: 5, right: 5, bottom: 0, left: 60 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis
                    dataKey="time"
                    tickFormatter={(v) => formatTime(v)}
                    tick={{ fontSize: 10, fill: "#6b7280", fontFamily: "monospace" }}
                    tickLine={false}
                    axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                    interval={30}
                  />
                  <YAxis
                    domain={["auto", "auto"]}
                    tick={{ fontSize: 10, fill: "#6b7280", fontFamily: "monospace" }}
                    tickLine={false}
                    axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                    tickFormatter={(v) => v.toFixed(2)}
                    width={58}
                  />
                  <Tooltip
                    contentStyle={{ background: "#1a1f2e", border: "1px solid #2d3748", borderRadius: 6, fontSize: 11, fontFamily: "monospace" }}
                    labelStyle={{ color: "#9ca3af" }}
                    labelFormatter={(v) => `${formatDate(v)} ${formatTime(v)}`}
                    formatter={(value: number, name: string) => [value.toFixed(4), name.toUpperCase()]}
                  />
                  <Bar dataKey="close" shape={<CustomCandleShape />} isAnimationActive={false}>
                    {chartData.slice(-200).map((entry, index) => (
                      <Cell key={index} fill={entry.isGreen ? "#22c55e" : "#ef4444"} />
                    ))}
                  </Bar>
                  {supportLevels.map((f) => (
                    <ReferenceLine
                      key={`S-${f.price}`}
                      y={f.price}
                      stroke="#22c55e"
                      strokeDasharray="4 3"
                      strokeWidth={1.5}
                      label={{ value: `S:${f.price}`, position: "right", fontSize: 9, fill: "#22c55e", fontFamily: "monospace" }}
                    />
                  ))}
                  {resistanceLevels.map((f) => (
                    <ReferenceLine
                      key={`R-${f.price}`}
                      y={f.price}
                      stroke="#ef4444"
                      strokeDasharray="4 3"
                      strokeWidth={1.5}
                      label={{ value: `R:${f.price}`, position: "right", fontSize: 9, fill: "#ef4444", fontFamily: "monospace" }}
                    />
                  ))}
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* TSI chart */}
        {tsiChartData.length > 0 && (
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <span className="text-sm font-mono font-semibold">TSI · TREND STRENGTH INDEX (55)</span>
              <span className="ml-3 text-xs font-mono text-muted-foreground">0=Choppy · 100=Strong Trend</span>
            </div>
            <div className="p-4">
              <ResponsiveContainer width="100%" height={130}>
                <ComposedChart data={tsiChartData} margin={{ top: 5, right: 5, bottom: 0, left: 35 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="i" hide />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fontSize: 10, fill: "#6b7280", fontFamily: "monospace" }}
                    tickLine={false}
                    axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                    width={32}
                  />
                  <Tooltip
                    contentStyle={{ background: "#1a1f2e", border: "1px solid #2d3748", borderRadius: 6, fontSize: 11, fontFamily: "monospace" }}
                    formatter={(v: number) => [v.toFixed(1), "TSI"]}
                  />
                  <ReferenceLine y={70} stroke="#22c55e" strokeDasharray="3 3" strokeWidth={1}
                    label={{ value: "STRONG 70", position: "right", fontSize: 9, fill: "#22c55e", fontFamily: "monospace" }} />
                  <ReferenceLine y={40} stroke="#f59e0b" strokeDasharray="3 3" strokeWidth={1}
                    label={{ value: "MOD 40", position: "right", fontSize: 9, fill: "#f59e0b", fontFamily: "monospace" }} />
                  <Line type="monotone" dataKey="value" stroke="#00d4ff" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* MACD chart */}
        {macdChartData.length > 0 && (
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <span className="text-sm font-mono font-semibold">MACD (21, 55, 21)</span>
              <span className="ml-3 text-xs font-mono text-muted-foreground">
                MACD: <span className={macd && macd.macd >= 0 ? "text-green-400" : "text-red-400"}>{macd?.macd.toFixed(5)}</span>
                {" · "}Signal: {macd?.signal.toFixed(5)}
              </span>
            </div>
            <div className="p-4">
              <ResponsiveContainer width="100%" height={130}>
                <ComposedChart data={macdChartData} margin={{ top: 5, right: 5, bottom: 0, left: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="i" hide />
                  <YAxis
                    tick={{ fontSize: 10, fill: "#6b7280", fontFamily: "monospace" }}
                    tickLine={false}
                    axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                    width={38}
                    tickFormatter={(v) => v.toFixed(4)}
                  />
                  <Tooltip
                    contentStyle={{ background: "#1a1f2e", border: "1px solid #2d3748", borderRadius: 6, fontSize: 11, fontFamily: "monospace" }}
                    formatter={(v: number, name: string) => [v.toFixed(5), name.toUpperCase()]}
                  />
                  <ReferenceLine y={0} stroke="rgba(255,255,255,0.2)" strokeWidth={1} />
                  <Bar dataKey="histogram" isAnimationActive={false}>
                    {macdChartData.map((entry, index) => (
                      <Cell key={index} fill={entry.histogram >= 0 ? "#22c55e" : "#ef4444"} opacity={0.75} />
                    ))}
                  </Bar>
                  <Line type="monotone" dataKey="macd" stroke="#00d4ff" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="signal" stroke="#f59e0b" strokeWidth={1} dot={false} strokeDasharray="3 2" isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Fractal levels table */}
        {fractals.length > 0 && (
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <span className="text-sm font-mono font-semibold">RECENT FRACTAL LEVELS</span>
            </div>
            <div className="p-4">
              <table className="w-full text-sm font-mono" data-testid="fractal-table">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase">
                    <th className="text-left py-1">Type</th>
                    <th className="text-right py-1">Price</th>
                    <th className="text-right py-1">Index</th>
                  </tr>
                </thead>
                <tbody>
                  {[...fractals].reverse().map((f, i) => (
                    <tr key={i} className="border-t border-border/30">
                      <td className={`py-1.5 font-bold ${f.type === "SUPPORT" ? "signal-uptrend" : "signal-downtrend"}`}>
                        {f.type}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">{f.price.toFixed(4)}</td>
                      <td className="py-1.5 text-right text-muted-foreground">{f.index}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Structure */}
        {symData?.structure && (
          <div className="rounded-lg border border-border bg-card p-4 font-mono text-xs text-muted-foreground">
            <div className="font-bold text-foreground mb-2 text-sm">MARKET STRUCTURE</div>
            <div>{symData.structure.description}</div>
          </div>
        )}
      </main>
    </div>
  );
}
