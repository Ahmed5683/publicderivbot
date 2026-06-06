import {
  useGetChartData,
  getGetChartDataQueryKey,
  useGetMarketAnalysis,
  useGetSymbolList,
} from "@workspace/api-client-react";
import { useParams, useLocation } from "wouter";
import { Skeleton } from "@/components/ui/skeleton";
import { CandleChart } from "@/components/CandleChart";
import type { SymbolAnalysis } from "@workspace/api-client-react";

const ALL_SYMBOLS = [
  "1HZ10V","R_10","1HZ15V","1HZ25V","R_25",
  "1HZ30V","1HZ50V","R_50","1HZ75V","R_75",
  "1HZ90V","1HZ100V","R_100",
];

const LEGEND = [
  { key: "HH", label: "Higher High", color: "#22c55e" },
  { key: "HL", label: "Higher Low",  color: "#4ade80" },
  { key: "LH", label: "Lower High",  color: "#ef4444" },
  { key: "LL", label: "Lower Low",   color: "#fca5a5" },
];

const STATE_COLOR: Record<string, string> = {
  PULLBACK:         "text-amber-400",
  BOS_CONTINUATION: "text-cyan-400",
  CHoCH_REVERSAL:   "text-purple-400",
  IN_TREND:         "",
  CONSOLIDATION:    "text-gray-400",
};

function StatPill({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-[#111827] border border-[#1e293b] rounded px-3 py-1.5">
      <div className="text-[10px] text-[#6b7280] font-mono uppercase tracking-wide">{label}</div>
      <div className={`text-xs font-bold font-mono mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}

export default function SymbolDetail() {
  const { symbol } = useParams<{ symbol: string }>();
  const [, setLocation] = useLocation();

  const { data: symbolList } = useGetSymbolList();

  const { data: chart, isLoading: chartLoading } = useGetChartData(symbol!, {
    query: {
      enabled: !!symbol,
      queryKey: getGetChartDataQueryKey(symbol!),
    },
  });

  const { data: marketData } = useGetMarketAnalysis();
  const symData: SymbolAnalysis | undefined = marketData?.symbols.find(
    (s: SymbolAnalysis) => s.symbol === symbol
  );

  const tsi  = symData?.tsi;
  const macd = symData?.macd;

  const tsiColor =
    tsi?.is_oversold  ? "text-green-400" :
    tsi?.is_overbought ? "text-red-400"  : "text-cyan-400";
  const tsiTag =
    tsi?.is_oversold  ? "OVERSOLD"  :
    tsi?.is_overbought ? "OVERBOUGHT" : "NEUTRAL";

  const stateColor =
    symData?.trend === "UPTREND" && symData?.state === "IN_TREND"   ? "text-green-400" :
    symData?.trend === "DOWNTREND" && symData?.state === "IN_TREND" ? "text-red-400"   :
    symData ? (STATE_COLOR[symData.state] ?? "text-foreground") : "text-foreground";

  const updatedTime = chart?.last_updated
    ? new Date(chart.last_updated + "Z").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "";

  // Build symbol options — use fetched list or fall back to constant
  const symbolOptions = (symbolList ?? ALL_SYMBOLS.map(s => ({ symbol: s, name: s, multiplier: 0 })));

  return (
    <div className="min-h-screen bg-[#0d1117] text-foreground">
      {/* ── Top bar ─────────────────────────────────────────── */}
      <div className="border-b border-[#1e293b] px-5 py-3 flex items-center gap-4">
        <button
          className="text-[10px] font-mono text-[#6b7280] hover:text-primary transition-colors px-2 py-1 border border-[#1e293b] rounded"
          onClick={() => setLocation("/")}
        >
          ← BACK
        </button>

        {/* Title */}
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-lg font-bold font-mono text-primary">{symbol}</span>
          <span className="text-xs text-[#6b7280] font-mono hidden sm:block">
            Candlestick · 1m · {chart?.bar_count ?? "…"} bars
          </span>
          {symData && (
            <span className={`text-xs font-bold font-mono ${stateColor}`}>
              {symData.state.replace(/_/g, " ")} · {symData.trend}
            </span>
          )}
        </div>

        {/* Right: dropdown + updated time */}
        <div className="ml-auto flex items-center gap-3">
          {updatedTime && (
            <span className="text-[10px] font-mono text-[#6b7280] hidden md:block">
              updated {updatedTime}
            </span>
          )}
          {symData && (
            <span className="text-base font-bold font-mono tabular-nums">
              {symData.price.toLocaleString(undefined, { minimumFractionDigits: 4 })}
            </span>
          )}

          {/* Symbol dropdown */}
          <select
            value={symbol}
            onChange={(e) => setLocation(`/symbol/${e.target.value}`)}
            className="bg-[#111827] border border-[#1e293b] text-sm font-mono text-foreground rounded px-3 py-1.5 focus:outline-none focus:border-primary cursor-pointer hover:border-[#334155] transition-colors"
          >
            {symbolOptions.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Legend ──────────────────────────────────────────── */}
      <div className="px-5 py-2 flex items-center gap-5 border-b border-[#1e293b] bg-[#0d1117]">
        {LEGEND.map(({ key, label, color }) => (
          <div key={key} className="flex items-center gap-1.5 text-xs font-mono text-[#9ca3af]">
            <span style={{ color }} className="text-base leading-none">●</span>
            <span style={{ color }} className="font-bold">{key}</span>
            <span className="text-[#6b7280]">— {label}</span>
          </div>
        ))}
        {chart?.trend && (
          <span className={`ml-auto text-xs font-bold font-mono ${
            chart.trend === "UPTREND" ? "text-green-400" :
            chart.trend === "DOWNTREND" ? "text-red-400" : "text-gray-400"
          }`}>
            {chart.trend}
          </span>
        )}
      </div>

      {/* ── Chart subtitle ───────────────────────────────────── */}
      <div className="px-5 pt-2 pb-1">
        <span className="text-[11px] font-mono text-[#6b7280]">
          {symbol} — last {chart?.bar_count ?? 1000} candles (1m)
        </span>
      </div>

      {/* ── Stats row ───────────────────────────────────────── */}
      {symData && (
        <div className="px-5 pb-2 flex flex-wrap gap-2">
          <StatPill label="Volatility"      value={`${symData.volatility.toFixed(1)}%`}  color="text-foreground" />
          <StatPill label="Fractals(55)"    value={`${symData.fractal_count}`}            color="text-cyan-400" />
          {symData.support    && <StatPill label="Support"    value={symData.support.toFixed(4)}    color="text-green-400" />}
          {symData.resistance && <StatPill label="Resistance" value={symData.resistance.toFixed(4)} color="text-red-400"   />}
          {tsi && (
            <StatPill
              label="TSI Pearson r(55)"
              value={`${tsi.value >= 0 ? "+" : ""}${tsi.value.toFixed(3)}  ${tsiTag}`}
              color={tsiColor}
            />
          )}
          {macd && (
            <StatPill
              label="MACD Hist(21,55,21)"
              value={`${macd.histogram >= 0 ? "+" : ""}${macd.histogram.toFixed(5)}`}
              color={macd.histogram >= 0 ? "text-green-400" : "text-red-400"}
            />
          )}
        </div>
      )}

      {/* ── Description ──────────────────────────────────────── */}
      {symData?.description && (
        <div className="px-5 pb-2">
          <div className="text-xs font-mono text-[#6b7280] bg-[#111827] border border-[#1e293b] rounded px-3 py-2">
            {symData.description}
          </div>
        </div>
      )}

      {/* ── Canvas chart ─────────────────────────────────────── */}
      <div className="px-5 pb-5">
        <div className="rounded-lg border border-[#1e293b] bg-[#0d1117] overflow-hidden">
          {chartLoading ? (
            <Skeleton className="h-[660px] w-full rounded-lg" />
          ) : (
            <CandleChart
              candles={chart?.candles ?? []}
              markers={chart?.markers ?? []}
              hhLevel={chart?.hh_level}
              hlLevel={chart?.hl_level}
              lhLevel={chart?.lh_level}
              llLevel={chart?.ll_level}
              trend={chart?.trend}
              tsiValues={tsi?.values ?? []}
              macdValues={macd?.values ?? []}
              macdSignalValues={macd?.signal_values ?? []}
              macdHistValues={macd?.histogram_values ?? []}
            />
          )}
        </div>
      </div>

      {/* ── Footer ───────────────────────────────────────────── */}
      <div className="px-5 pb-5 text-[10px] font-mono text-[#4b5563]">
        TSI = Pearson r (−1 to +1) · Oversold &lt; −0.7 · Overbought &gt; +0.7 ·
        Fractals period=55 · Green=HH/HL · Red=LH/LL
      </div>
    </div>
  );
}
