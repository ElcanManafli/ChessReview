import type { CSSProperties } from "react";
import type { MoveClassification } from "@/lib/chess-api";
import { cn } from "@/lib/utils";

const SYMBOLS: Record<MoveClassification, { text: string; className: string }> = {
  book: { text: "📖︎", className: "book" },
  brilliant: { text: "!!", className: "brilliant" },
  great: { text: "!", className: "great" },
  best: { text: "★", className: "best" },
  good: { text: "✓", className: "good" },
  inaccuracy: { text: "?!", className: "inaccuracy" },
  mistake: { text: "?", className: "mistake" },
  blunder: { text: "??", className: "blunder" },
  missed_win: { text: "❌", className: "missed-win" },
};

export function MoveEvaluationSymbol({
  classification,
  className,
  style,
}: {
  classification: MoveClassification;
  className?: string;
  style?: CSSProperties;
}) {
  const symbol = SYMBOLS[classification];
  return (
    <span
      aria-label={symbol.text}
      className={cn(
        "move-evaluation-symbol",
        `move-evaluation-symbol--${symbol.className}`,
        className,
      )}
      style={style}
    >
      {symbol.text}
    </span>
  );
}
