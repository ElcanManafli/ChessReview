import { useMemo } from "react";
import type { GameAnalysis, MoveClassification } from "@/lib/chess-api";
import { CLASSIFICATION_META } from "./ClassificationBadge";
import { MoveEvaluationSymbol } from "./MoveEvaluationSymbol";
import { cn } from "@/lib/utils";

const ORDER: MoveClassification[] = [
  "book",
  "brilliant",
  "great",
  "best",
  "excellent",
  "good",
  "inaccuracy",
  "mistake",
  "blunder",
  "miss",
];

function AccuracyRow({ label, value, dark }: { label: string; value: number; dark?: boolean }) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className={cn("font-medium", dark ? "text-muted-foreground" : "text-foreground")}>
          {label}
        </span>
        <span className="font-mono text-base font-bold text-accent tabular-nums">
          {value.toFixed(1)}%
        </span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-secondary">
        <div
          className="h-full rounded-full transition-[width] duration-700"
          style={{ width: `${value}%`, backgroundImage: "var(--gradient-accent)" }}
        />
      </div>
    </div>
  );
}

export function GameSummary({ analysis }: { analysis: GameAnalysis }) {
  const counts = useMemo(() => {
    const totals = new Map<MoveClassification, { white: number; black: number }>();
    for (const move of analysis.moves) {
      const count = totals.get(move.classification) ?? { white: 0, black: 0 };
      count[move.color === "w" ? "white" : "black"] += 1;
      totals.set(move.classification, count);
    }
    return ORDER.flatMap((key) => {
      const count = totals.get(key);
      return count ? [{ key, ...count }] : [];
    });
  }, [analysis.moves]);

  return (
    <div className="panel space-y-4 p-4">
      <h3 className="text-sm font-semibold">Game Summary</h3>

      <div className="space-y-3">
        <AccuracyRow label="White Accuracy" value={analysis.whiteAccuracy} />
        <AccuracyRow label="Black Accuracy" value={analysis.blackAccuracy} dark />
      </div>

      {counts.length > 0 && (
        <div className="space-y-1.5 border-t border-border pt-3">
          {counts.map((row) => {
            const meta = CLASSIFICATION_META[row.key];
            return (
              <div key={row.key} className="flex items-center gap-2 text-xs">
                <MoveEvaluationSymbol
                  classification={row.key}
                  className={cn("size-3.5 shrink-0", meta.text)}
                />
                <span className={cn("min-w-0 flex-1 truncate font-medium", meta.text)}>
                  {meta.label}
                </span>
                <span className="w-8 shrink-0 text-right font-mono tabular-nums">{row.white}</span>
                <span className="w-8 shrink-0 text-right font-mono tabular-nums text-muted-foreground">
                  {row.black}
                </span>
              </div>
            );
          })}
          <div className="flex items-center gap-2 pt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            <span className="min-w-0 flex-1" />
            <span className="w-8 text-right">White</span>
            <span className="w-8 text-right">Black</span>
          </div>
        </div>
      )}

      <p className="border-t border-border pt-3 text-sm leading-relaxed text-muted-foreground">
        {analysis.summary}
      </p>
      {analysis.termination && (
        <p className="text-xs font-medium text-muted-foreground">
          Ended by {analysis.termination.reason} ({analysis.termination.result}).
        </p>
      )}
    </div>
  );
}
