import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AnalyzedMove } from "@/lib/chess-api";

export function EvaluationAdvantageGraph({ moves }: { moves: AnalyzedMove[] }) {
  const points = [
    { ply: 0, position: "Start", evaluation: 0 },
    ...moves.map((move) => ({
      ply: move.ply + 1,
      position: `${move.moveNumber}${move.color === "w" ? "." : "..."}`,
      evaluation: Math.max(-10, Math.min(10, move.evaluation)),
    })),
  ];

  return (
    <section className="panel p-4" aria-label="Evaluation advantage graph">
      <h2 className="mb-3 text-sm font-semibold">Evaluation advantage</h2>
      {moves.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Analyze a game to see the evaluation graph.
        </p>
      ) : (
        <div className="h-56 w-full" role="img" aria-label="White-centric engine evaluation by ply">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
              <XAxis
                dataKey="ply"
                tick={{ fontSize: 11 }}
                tickFormatter={(ply: number) =>
                  ply === 0 ? "Start" : `${Math.ceil(ply / 2)}${ply % 2 ? "." : "..."}`
                }
                minTickGap={24}
              />
              <YAxis
                domain={[-10, 10]}
                tick={{ fontSize: 11 }}
                tickFormatter={(value: number) => `${value > 0 ? "+" : ""}${value}`}
                width={42}
              />
              <ReferenceLine y={0} stroke="currentColor" strokeDasharray="4 4" />
              <Tooltip
                formatter={(value) => [`${Number(value).toFixed(2)} pawns`, "White evaluation"]}
                labelFormatter={(_, payload) => payload?.[0]?.payload?.position ?? "Position"}
              />
              <Line
                type="monotone"
                dataKey="evaluation"
                stroke="var(--primary)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        Positive scores favor White; negative scores favor Black. Values are capped at ±10 pawns.
      </p>
    </section>
  );
}
