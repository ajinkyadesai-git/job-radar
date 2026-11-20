import { fitSegments } from "../format";

/** The fit score as five segments, like a signal meter. Unscored jobs say so. */
export function FitMeter({ score }: { score: number | null }) {
  const lit = fitSegments(score);
  if (lit === null) return <span className="fit-none">Not scored yet</span>;
  return (
    <span className="fit" role="img" aria-label={`Fit ${Math.round((score ?? 0) * 100)} out of 100`}>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} className={i < lit ? "seg on" : "seg"} />
      ))}
      <span className="fit-num">{Math.round((score ?? 0) * 100)}</span>
    </span>
  );
}
