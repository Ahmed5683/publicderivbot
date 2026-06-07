import { useGetMarketAnalysis, getGetMarketAnalysisQueryKey } from "@workspace/api-client-react";
import { useLocation } from "wouter";
import { Skeleton } from "@/components/ui/skeleton";
import { useState, useEffect } from "react";
import type { SymbolAnalysis } from "@workspace/api-client-react";

type State = "PULLBACK" | "BOS_CONTINUATION" | "CHoCH_REVERSAL" | "IN_TREND";
type Trend = "UPTREND" | "DOWNTREND";

function stateLabel(state: State, trend: Trend): string {
  if (state === "PULLBACK")         return trend === "UPTREND" ? "PULLBACK ▲" : "PULLBACK ▼";
  if (state === "BOS_CONTINUATION") return trend === "UPTREND" ? "BOS ▲" : "BOS ▼";
  if (state === "CHoCH_REVERSAL")   return trend === "UPTREND" ? "CHoCH ▲" : "CHoCH ▼";
  return trend === "UPTREND" ? "UPTREND ▲" : "DOWNTREND ▼";
}

function stateClass(state: State, trend: Trend): string {
  if (state === "PULLBACK")         return "bg-amber-500/10 text-amber-400 border-amber-500/30";
  if (state === "BOS_CONTINUATION") return "bg-cyan-500/10 text-cyan-400 border-cyan-500/30";
  if (state === "CHoCH_REVERSAL")   return "bg-purple-500/10 text-purple-400 border-purple-500/30";
  return trend === "UPTREND"
    ? "bg-green-500/10 text-green-400 border-green-500/30"
    : "bg-red-500/10 text-red-400 border-red-500/30";
}

function trendArrow(trend: Trend) {
  return trend === "UPTREND"
    ? <span className="text-green-400 font-bold">▲</span>
    : <span className="text-red-400 font-bold">▼</span>;
}

function tsiDisplay(tsi: SymbolAnalysis["tsi"]) {
  if (!tsi) return { label: "—", color: "text-muted-foreground", slope: 0, slopeColor: "text-gray-500", slopeArrow: "→" };
  const vals = tsi.values ?? [];
  const slope = vals.length >= 5 ? vals[vals.length - 1] - vals[vals.length - 5] : 0;
  const slopeArrow = slope >  0.003 ? "↑" : slope < -0.003 ? "↓" : "→";
  const slopeColor = slope >  0.003 ? "text-green-400" : slope < -0.003 ? "text-red-400" : "text-gray-500";
  if (tsi.is_oversold)   return { label: `${tsi.value.toFixed(3)} OVS`, color: "text-green-400", slope, slopeColor, slopeArrow };
  if (tsi.is_overbought) return { label: `${tsi.value.toFixed(3)} OVB`, color: "text-red-400",   slope, slopeColor, slopeArrow };
  return { label: tsi.value.toFixed(3), color: "text-cyan-400", slope, slopeColor, slopeArrow };
}

interface SummaryCardProps {
  label: string;
  count: number;
  colorClass: string;
  icon: string;
}

function SummaryCard({ label, count, colorClass, icon }: SummaryCardProps) {
  return (
    <div className={`rounded-lg border p-4 flex flex-col gap-1 ${colorClass}`}>
      <div className="text-xs font-mono uppercase tracking-widest opacity-70">{icon} {label}</div>
      <div className="text-3xl font-bold font-mono tabular-nums">{count}</div>
    </div>
  );
}

function CountdownBar({ seconds }: { seconds: number }) {
  const pct = ((60 - seconds) / 60) * 100;
  return (
    <div className="w-full h-0.5 bg-muted rounded-full overflow-hidden">
      <div className="h-full bg-primary transition-all duration-1000" style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function Dashboard() {
  const [, setLocation] = useLocation();
  const [countdown, setCountdown] = useState(60);
  const { data, isLoading, dataUpdatedAt, refetch } = useGetMarketAnalysis({
    query: { refetchInterval: 60_000, queryKey: getGetMarketAnalysisQueryKey() },
  });

  useEffect(() => {
    setCountdown(60);
    const id = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { refetch(); return 60; }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [dataUpdatedAt, refetch]);

  const symbols: SymbolAnalysis[] = data?.symbols ?? [];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold font-mono tracking-tight text-primary">
            DERIV MARKET SCANNER
          </h1>
          <p className="text-xs text-muted-foreground font-mono mt-0.5">
            Fractals(36) · TSI Pearson r(55) · MACD(21,55,21) · 500 candles for detection
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs font-mono text-muted-foreground">
            {data?.timestamp
              ? new Date(data.timestamp + "Z").toLocaleTimeString()
              : "Scanning..."}
          </div>
          <div className="text-xs font-mono text-muted-foreground mt-1">
            Next scan in <span className="text-primary font-bold">{countdown}s</span>
          </div>
          <div className="mt-1 w-32">
            <CountdownBar seconds={countdown} />
          </div>
        </div>
      </header>

      <main className="px-6 py-5 space-y-6">
        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {isLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 rounded-lg" />
            ))
          ) : (
            <>
              <SummaryCard label="Pullbacks" count={data?.pullback_count ?? 0} colorClass="bg-amber-500/10 border-amber-500/25 text-amber-400"    icon="↩" />
              <SummaryCard label="BOS"       count={data?.bos_count ?? 0}      colorClass="bg-cyan-500/10 border-cyan-500/25 text-cyan-400"       icon="⬡" />
              <SummaryCard label="CHoCH"     count={data?.choch_count ?? 0}    colorClass="bg-purple-500/10 border-purple-500/25 text-purple-400"  icon="⚡" />
              <SummaryCard label="In Trend"  count={data?.trending_count ?? 0} colorClass="bg-green-500/10 border-green-500/25 text-green-400"     icon="◎" />
            </>
          )}
        </div>

        {/* Symbol table */}
        <div className="rounded-lg border border-border overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-card flex items-center justify-between">
            <span className="text-sm font-mono font-semibold">MARKET STATE · 13 SYMBOLS</span>
            <span className="text-xs font-mono text-muted-foreground">
              {symbols.length > 0 ? `${symbols.length} scanned` : isLoading ? "Scanning first run (~60s)…" : ""}
            </span>
          </div>

          {isLoading && symbols.length === 0 ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm font-mono" data-testid="symbol-table">
                <thead>
                  <tr className="border-b border-border text-xs text-muted-foreground uppercase tracking-wider">
                    <th className="text-left px-4 py-3">Symbol</th>
                    <th className="text-right px-4 py-3">Price</th>
                    <th className="text-right px-4 py-3">Vol%</th>
                    <th className="text-center px-4 py-3">State</th>
                    <th className="text-center px-4 py-3">TSI(r)</th>
                    <th className="text-center px-4 py-3">TSI Δ</th>
                    <th className="text-right px-4 py-3">MACD Hist</th>
                    <th className="text-right px-4 py-3">Frac</th>
                    <th className="text-left px-4 py-3">S / R</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.map((sym: SymbolAnalysis) => {
                    const { label: tsiLbl, color: tsiClr, slope, slopeColor, slopeArrow } = tsiDisplay(sym.tsi);
                    return (
                      <tr
                        key={sym.symbol}
                        className="border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors"
                        onClick={() => setLocation(`/symbol/${sym.symbol}`)}
                        data-testid={`row-symbol-${sym.symbol}`}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            {trendArrow(sym.trend as Trend)}
                            <div>
                              <div className="font-semibold text-foreground">{sym.symbol}</div>
                              <div className="text-xs text-muted-foreground">{sym.name}</div>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          {sym.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                          {sym.volatility.toFixed(1)}%
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold border ${stateClass(sym.state as State, sym.trend as Trend)}`}
                            data-testid={`status-${sym.symbol}`}>
                            {stateLabel(sym.state as State, sym.trend as Trend)}
                          </span>
                        </td>
                        <td className={`px-4 py-3 text-center text-xs font-bold tabular-nums ${tsiClr}`}>
                          {tsiLbl}
                        </td>
                        <td className="px-4 py-3 text-center text-xs font-bold tabular-nums">
                          <span className={slopeColor}>
                            {slopeArrow} {slope !== 0 ? Math.abs(slope).toFixed(4) : "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-xs">
                          {sym.macd ? (
                            <span className={sym.macd.histogram >= 0 ? "text-green-400" : "text-red-400"}>
                              {sym.macd.histogram >= 0 ? "+" : ""}{sym.macd.histogram.toFixed(4)}
                            </span>
                          ) : "—"}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">
                          {sym.fractal_count}
                        </td>
                        <td className="px-4 py-3 text-left text-xs">
                          {sym.support && sym.resistance ? (
                            <>
                              <span className="text-green-400">S:{sym.support.toFixed(3)}</span>
                              {" "}
                              <span className="text-red-400">R:{sym.resistance.toFixed(3)}</span>
                            </>
                          ) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Pullback highlights */}
        {!isLoading && symbols.filter(s => s.state === "PULLBACK").length > 0 && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
            <div className="text-xs font-mono text-amber-400 font-semibold mb-3 uppercase tracking-widest">
              ↩ Potential Entry · Pullbacks to Key Level
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {symbols.filter(s => s.state === "PULLBACK").map(s => (
                <div
                  key={s.symbol}
                  className="rounded border border-amber-500/20 bg-card p-3 cursor-pointer hover:border-amber-500/50 transition-colors"
                  onClick={() => setLocation(`/symbol/${s.symbol}`)}
                  data-testid={`pullback-card-${s.symbol}`}
                >
                  <div className="flex justify-between items-start mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-foreground">{s.symbol}</span>
                      <span className={`text-xs font-bold ${s.trend === "UPTREND" ? "text-green-400" : "text-red-400"}`}>
                        {s.trend === "UPTREND" ? "BUY" : "SELL"}
                      </span>
                    </div>
                    <span className="text-xs font-mono text-muted-foreground">{s.price.toFixed(4)}</span>
                  </div>
                  <div className="text-xs text-muted-foreground leading-snug">{s.description}</div>
                  {s.tsi && (
                    <div className={`text-xs font-mono mt-1.5 font-bold ${s.tsi.is_oversold ? "text-green-400" : s.tsi.is_overbought ? "text-red-400" : "text-cyan-400"}`}>
                      TSI: {s.tsi.value.toFixed(3)}
                      {s.tsi.is_oversold ? " · OVERSOLD ✓" : s.tsi.is_overbought ? " · OVERBOUGHT ✓" : ""}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="text-xs font-mono text-muted-foreground border-t border-border pt-4">
          TSI = Pearson r (−1 to +1) · Oversold &lt; −0.7 · Overbought &gt; +0.7 · Fractals period=36 ·
          BOS = close above HH or below LL · CHoCH = close above LH or below HL ·
          Pullback = TSI slope opposes trend · TSI Δ = slope over last 5 bars
        </div>
      </main>
    </div>
  );
}
