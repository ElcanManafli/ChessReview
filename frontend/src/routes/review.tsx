import { createFileRoute, Link } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, LineChart, ListOrdered, Trophy } from "lucide-react";
import { AnalysisBoard } from "@/components/chess/AnalysisBoard";
import { EvaluationBar } from "@/components/chess/EvaluationBar";
import { MoveList } from "@/components/chess/MoveList";
import { PlaybackControls } from "@/components/chess/PlaybackControls";
import { GameSummary } from "@/components/chess/GameSummary";
import { MoveEvaluationSymbol } from "@/components/chess/MoveEvaluationSymbol";
import { ANALYSIS_STORAGE_KEY, type GameAnalysis } from "@/lib/chess-api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/review")({
  head: () => ({
    meta: [
      { title: "Game Review & Analysis — ChessReview Analytics" },
      {
        name: "description",
        content:
          "Replay your game move by move with an evaluation bar, brilliant/blunder classifications and accuracy percentages for White and Black.",
      },
      { property: "og:title", content: "Game Review & Analysis — ChessReview Analytics" },
      {
        property: "og:description",
        content: "Interactive board playback, engine evaluation and per-move quality badges.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ReviewPage,
});

type TabKey = "moves" | "engine" | "summary";

const TABS: { key: TabKey; label: string; icon: typeof LineChart }[] = [
  { key: "moves", label: "Moves", icon: ListOrdered },
  { key: "engine", label: "Engine", icon: LineChart },
  { key: "summary", label: "Summary", icon: Trophy },
];

function ReviewPage() {
  const [analysis, setAnalysis] = useState<GameAnalysis | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [tab, setTab] = useState<TabKey>("moves");

  useEffect(() => {
    const stored = sessionStorage.getItem(ANALYSIS_STORAGE_KEY);
    if (!stored) return;
    try {
      setAnalysis(JSON.parse(stored) as GameAnalysis);
      setActiveIndex(-1);
    } catch {
      sessionStorage.removeItem(ANALYSIS_STORAGE_KEY);
    }
  }, []);

  const moves = analysis?.moves ?? [];
  const startFen = analysis?.startFen ?? "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  const lastIndex = moves.length - 1;
  const canPrev = activeIndex > -1;
  const canNext = activeIndex < lastIndex;

  const goNext = useCallback(
    () => setActiveIndex((i) => Math.min(i + 1, moves.length - 1)),
    [moves.length],
  );
  const goPrev = useCallback(() => setActiveIndex((i) => Math.max(i - 1, -1)), []);

  useEffect(() => {
    if (!isPlaying) return;
    if (activeIndex >= lastIndex) {
      setIsPlaying(false);
      return;
    }
    const timer = setTimeout(goNext, 800);
    return () => clearTimeout(timer);
  }, [isPlaying, activeIndex, lastIndex, goNext]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && /INPUT|TEXTAREA/.test(target.tagName)) return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setIsPlaying(false);
        goNext();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setIsPlaying(false);
        goPrev();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext, goPrev]);

  const current = activeIndex >= 0 ? moves[activeIndex] : undefined;
  const position = current?.fenAfter ?? startFen;
  const evaluation = current?.evaluation ?? analysis?.finalEvaluation ?? 0;

  const label = useMemo(() => {
    if (!current) {
      if (moves.length) return "Starting position";
      return analysis ? "Position loaded" : "Starting position — no game loaded";
    }
    return `${current.moveNumber}${current.color === "w" ? "." : "..."} ${current.san}`;
  }, [analysis, current, moves.length]);

  const select = (index: number) => {
    setIsPlaying(false);
    setActiveIndex(index);
  };

  const rightPanel = (
    <>
      <div className={cn(tab === "moves" ? "block" : "hidden", "lg:block")}>
        <MoveList moves={moves} activeIndex={activeIndex} onSelect={select} />
      </div>
      <div className={cn(tab === "engine" ? "block" : "hidden", "lg:block")}>
        <EvaluationBar
          evaluation={evaluation}
          score={current?.scoreAfter ?? analysis?.finalScore}
        />
      </div>
      <div className={cn(tab === "summary" ? "block" : "hidden", "lg:block")}>
        {analysis && <GameSummary analysis={analysis} />}
      </div>
    </>
  );

  return (
    <main className="min-h-screen px-4 py-6 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 sm:flex sm:justify-between">
          <Link
            to="/"
            className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium transition-colors hover:border-accent hover:text-accent"
          >
            <ArrowLeft className="size-4" />
            Back to Import
          </Link>
          <h1 className="truncate text-lg font-bold sm:text-2xl">Game Review &amp; Analysis</h1>
          <span className="hidden text-sm text-muted-foreground sm:inline">
            {moves.length} moves
          </span>
        </header>

        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,460px)_minmax(0,1fr)] lg:items-start">
          <section className="mx-auto w-full max-w-[460px]">
            <AnalysisBoard
              id="review-board"
              position={position}
              lastMove={current ? { from: current.from, to: current.to } : undefined}
              classification={current?.classification}
            />

            <div className="mt-4 flex items-center justify-center gap-2">
              <span className="font-mono text-sm font-semibold">{label}</span>
              {current && <MoveEvaluationSymbol classification={current.classification} />}
            </div>

            <div className="mt-4">
              <PlaybackControls
                onFirst={() => select(-1)}
                onPrev={() => {
                  setIsPlaying(false);
                  goPrev();
                }}
                onNext={() => {
                  setIsPlaying(false);
                  goNext();
                }}
                onLast={() => select(lastIndex)}
                onTogglePlay={() => setIsPlaying((p) => !p)}
                isPlaying={isPlaying}
                canPrev={canPrev}
                canNext={canNext}
              />
              <p className="mt-3 text-center text-xs text-muted-foreground">
                Tip: use the ← and → arrow keys to step through the game.
              </p>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex gap-1 rounded-lg border border-border bg-card p-1 lg:hidden">
              {TABS.map(({ key, label: tabLabel, icon: Icon }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setTab(key)}
                  className={cn(
                    "inline-flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-2 text-xs font-semibold transition-colors",
                    tab === key
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-accent",
                  )}
                >
                  <Icon className="size-3.5" />
                  {tabLabel}
                </button>
              ))}
            </div>
            {rightPanel}
          </section>
        </div>
      </div>
    </main>
  );
}
