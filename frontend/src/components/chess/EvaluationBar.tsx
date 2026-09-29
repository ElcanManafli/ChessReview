import { formatEval } from "@/lib/chess-api";

const MAX = 5;

export function EvaluationBar({
  evaluation,
  score,
}: {
  evaluation: number;
  score?: Parameters<typeof formatEval>[1];
}) {
  const clamped = Math.max(-MAX, Math.min(MAX, evaluation));
  const whiteShare = ((clamped + MAX) / (MAX * 2)) * 100;
  const leader = evaluation > 0.2 ? "White" : evaluation < -0.2 ? "Black" : "Even";

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Engine Evaluation</h3>
        <span className="font-mono text-lg font-bold text-accent tabular-nums">
          {formatEval(evaluation, score)}
        </span>
      </div>

      <div className="mt-3 h-4 w-full overflow-hidden rounded-full bg-foreground/85 ring-1 ring-border">
        <div
          className="h-full bg-background/90 transition-[width] duration-500 ease-out"
          style={{ width: `${100 - whiteShare}%` }}
        />
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] font-medium text-muted-foreground">
        <span>-5.0</span>
        <span className="text-accent">
          {leader === "Even" ? "Balanced" : `${leader} is better`}
        </span>
        <span>+5.0</span>
      </div>
    </div>
  );
}
