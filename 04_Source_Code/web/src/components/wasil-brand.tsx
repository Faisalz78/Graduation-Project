type WasilBrandProps = {
  compact?: boolean;
  inverted?: boolean;
  className?: string;
};

export function WasilBrand({ compact = false, inverted = false, className = "" }: WasilBrandProps) {
  return (
    <span
      className={`wasil-brand ${compact ? "is-compact" : ""} ${inverted ? "is-inverted" : ""} ${className}`.trim()}
      aria-label="واصل — Wasil"
    >
      <span className="wasil-wordmark" aria-hidden="true">
        <span className="wasil-arabic">واصل</span>
        <span className="wasil-swoosh" />
      </span>
      <span className="wasil-english" aria-hidden="true">
        Wasil
      </span>
    </span>
  );
}
