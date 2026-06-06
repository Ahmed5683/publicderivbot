import { useGetSymbolCandles, getGetSymbolCandlesQueryKey, useGetMarketAnalysis } from "@workspace/api-client-react";
import { useParams, useLocation } from "wouter";
import { Skeleton } from "@/components/ui/skeleton";
import { CandleChart } from "@/components/CandleChart";
import type { SymbolAnalysis, FractalLevel, MACDData, TSIData } from "@workspace/api-client-react";

function StatBadge({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="bg-card border border-border rounded px-3 py-2">
      <div className="text-xs text-muted-foreground font-mono uppercase tracking-wide">{label}</div>
      <div className={`text-sm font-bold font-mono mt-0.5 ${color}`}>{value}</div>
    </div>
  );
}

const STATE_COLORS: Record<string, string> = {
  PULLBACK:        "text-amber-400",
  BOS_CONTINUATION:"text-cyan-400",
  CHoCH_REVERSAL:  "text-purple-400",
  IN_TREND:        "text-foreground",
  CONSOLIDATION:   "text-gray-400",
};

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

  const macd: MACDData | undefined = symData?.macd;
  const tsi: TSIData | undefined = symData?.tsi;
  const fractals: FractalLevel[] = symData?.last_fractals ?? [];
  const supportLevels = fractals.filter(f => f.type === "SUPPORT").map(f => f.price);
  const resistanceLevels = fractals.filter(f => f.type === "RESISTANCE").map(f => f.price);

  const tsiValue = tsi?.value ?? 0;
  const tsiColor =
    tsi?.is_oversold  ? "text-green-400" :
    tsi?.is_overbought ? "text-red-400" :
    "text-cyan-400";
  const tsiLabel =
    tsi?.is_oversold  ? "OVERSOLD" :
    tsi?.is_overbought ? "OVERBOUGHT" :
    Math.abs(tsiValue) > 0.4 ? "TRENDING" : "NEUTRAL";

  const stateColor = symData
    ? (symData.trend === "UPTREND" && symData.state === "IN_TREND"
        ? "text-green-400"
        : symData.trend === "DOWNTREND" && symData.state === "IN_TREND"
          ? "text-red-400"
          : STATE_COLORS[symData.state] ?? "text-foreground")
    : "text-foreground";

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

      <main className="px-6 py-5 space-y-5">
        {/* Stats row */}
        {symData && (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            <StatBadge label="Volatility"   value={`${symData.volatility.toFixed(1)}%`}     color="text-foreground" />
            <StatBadge label="Fractals"     value={`${symData.fractal_count}`}              color="text-cyan-400" />
            {symData.support    && <StatBadge label="Support"    value={symData.support.toFixed(4)}    color="text-green-400" />}
            {symData.resistance && <StatBadge label="Resistance" value={symData.resistance.toFixed(4)} color="text-red-400" />}
            {tsi && (
              <StatBadge
                label="TSI(55) Pearson r"
                value={`${tsiValue >= 0 ? "+" : ""}${tsiValue.toFixed(3)} · ${tsiLabel}`}
                color={tsiColor}
              />
            )}
            {macd && (
              <StatBadge
                label="MACD Hist (21,55,21)"
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

        {/* Canvas chart */}
        <div className="rounded-lg border border-border bg-[#0d1117] overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <span className="text-sm font-mono font-semibold">
              {symbol} · 1000 CANDLES (1M) · Fractals(55) · TSI(55) · MACD(21,55,21)
            </span>
            {candlesLoading && (
              <span className="text-xs text-muted-foreground font-mono animate-pulse">Loading...</span>
            )}
          </div>
          <div className="p-2">
            {candlesLoading ? (
              <Skeleton className="h-[600px] w-full" />
            ) : (
              <CandleChart
                candles={candles ?? []}
                tsiValues={tsi?.values ?? []}
                macdValues={macd?.values ?? []}
                macdSignalValues={macd?.signal_values ?? []}
                macdHistValues={macd?.histogram_values ?? []}
                supportLevels={supportLevels}
                resistanceLevels={resistanceLevels}
              />
            )}
          </div>
        </div>

        {/* Fractal levels table */}
        {fractals.length > 0 && (
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <span className="text-sm font-mono font-semibold">FRACTAL LEVELS (Period=55)</span>
            </div>
            <div className="p-4">
              <table className="w-full text-sm font-mono" data-testid="fractal-table">
                <thead>
                  <tr className="text-xs text-muted-foreground uppercase">
                    <th className="text-left py-1">Type</th>
                    <th className="text-right py-1">Price</th>
                    <th className="text-right py-1">Bar Index</th>
                  </tr>
                </thead>
                <tbody>
                  {[...fractals].reverse().map((f, i) => (
                    <tr key={i} className="border-t border-border/30">
                      <td className={`py-1.5 font-bold ${f.type === "SUPPORT" ? "text-green-400" : "text-red-400"}`}>
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
            {symData.structure.bos_level && (
              <div className="mt-1">BOS Level: <span className="text-cyan-400">{symData.structure.bos_level.toFixed(4)}</span></div>
            )}
            {symData.structure.choch_level && (
              <div className="mt-1">CHoCH Level: <span className="text-purple-400">{symData.structure.choch_level.toFixed(4)}</span></div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
