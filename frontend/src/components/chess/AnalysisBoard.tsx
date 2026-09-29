import { useEffect, useState } from "react";
import { Chessboard } from "react-chessboard";
import type { MoveClassification } from "@/lib/chess-api";
import { MoveEvaluationSymbol } from "./MoveEvaluationSymbol";

interface AnalysisBoardProps {
  position: string;
  lastMove?: { from: string; to: string } | undefined;
  classification?: MoveClassification | undefined;
  animate?: boolean | undefined;
  id: string;
}

export function AnalysisBoard({
  position,
  lastMove,
  classification,
  animate = true,
  id,
}: AnalysisBoardProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const squareStyles: Record<string, React.CSSProperties> = {};
  if (lastMove) {
    const highlight = {
      boxShadow: "inset 0 0 0 3px var(--accent)",
      backgroundColor: "color-mix(in oklab, var(--accent) 26%, transparent)",
    };
    squareStyles[lastMove.from] = highlight;
    squareStyles[lastMove.to] = highlight;
  }

  if (!mounted) {
    return <div className="aspect-square w-full animate-pulse rounded-xl bg-secondary" />;
  }

  return (
    <div className="relative aspect-square overflow-hidden rounded-xl ring-1 ring-border">
      <Chessboard
        options={{
          id,
          position,
          allowDragging: false,
          animationDurationInMs: animate ? 200 : 0,
          showNotation: true,
          boardStyle: { width: "100%" },
          squareStyles,
          darkSquareStyle: { backgroundColor: "oklch(0.52 0.07 250)" },
          lightSquareStyle: { backgroundColor: "oklch(0.86 0.02 250)" },
        }}
      />
      {lastMove && classification && (
        <div className="board-evaluation-overlay" aria-hidden="true">
          <MoveEvaluationSymbol
            classification={classification}
            className="board-evaluation-symbol"
            style={{
              gridColumn: lastMove.to.charCodeAt(0) - 96,
              gridRow: 9 - Number(lastMove.to[1]),
            }}
          />
        </div>
      )}
    </div>
  );
}
