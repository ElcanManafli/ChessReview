import { useEffect, useRef } from "react";
import type { AnalyzedMove } from "@/lib/chess-api";
import { formatEval } from "@/lib/chess-api";
import { MoveEvaluationSymbol } from "./MoveEvaluationSymbol";
import { cn } from "@/lib/utils";

interface MoveListProps {
  moves: AnalyzedMove[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export function MoveList({ moves, activeIndex, onSelect }: MoveListProps) {
  const activeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeIndex]);

  if (moves.length === 0) {
    return (
      <div className="panel p-6 text-center text-sm text-muted-foreground">
        No game moves to review. Position loaded.
      </div>
    );
  }

  const pairs: { number: number; white?: AnalyzedMove; black?: AnalyzedMove }[] = [];
  moves.forEach((move) => {
    const last = pairs[pairs.length - 1];
    if (move.color === "w" || !last || last.black) {
      pairs.push({ number: move.moveNumber, [move.color === "w" ? "white" : "black"]: move });
    } else {
      last.black = move;
    }
  });

  const renderCell = (move?: AnalyzedMove) => {
    if (!move) return <div className="min-w-0 flex-1" />;
    const active = move.ply === activeIndex;
    return (
      <button
        ref={active ? activeRef : undefined}
        type="button"
        onClick={() => onSelect(move.ply)}
        className={cn(
          "flex min-w-0 flex-1 items-center justify-between gap-1 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
          active
            ? "bg-primary text-primary-foreground ring-1 ring-accent/60"
            : "hover:bg-secondary",
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate font-mono font-semibold">{move.san}</span>
          <MoveEvaluationSymbol classification={move.classification} />
        </span>
        <span
          className={cn(
            "shrink-0 font-mono text-[11px] tabular-nums",
            active ? "text-primary-foreground/80" : "text-muted-foreground",
          )}
        >
          {formatEval(move.evaluation, move.scoreAfter)}
        </span>
      </button>
    );
  };

  return (
    <div className="panel flex max-h-[420px] flex-col overflow-hidden">
      <div className="border-b border-border px-4 py-3 text-sm font-semibold">Moves</div>
      <div className="scroll-slim flex-1 overflow-y-auto p-2">
        {pairs.map((pair, i) => (
          <div key={i} className="flex items-center gap-1">
            <span className="w-8 shrink-0 text-right font-mono text-xs text-muted-foreground">
              {pair.number}.
            </span>
            {renderCell(pair.white)}
            {renderCell(pair.black)}
          </div>
        ))}
      </div>
    </div>
  );
}
