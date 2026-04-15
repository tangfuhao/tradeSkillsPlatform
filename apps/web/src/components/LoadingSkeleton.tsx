type LoadingSkeletonProps = {
  rows?: number;
  variant?: 'stat' | 'record' | 'inline';
};

function SkeletonLine({ width = '100%' }: { width?: string }) {
  return <span className="skeleton-line" style={{ width }} />;
}

export default function LoadingSkeleton({ rows = 3, variant = 'record' }: LoadingSkeletonProps) {
  if (variant === 'stat') {
    return (
      <div className="metric-grid">
        {Array.from({ length: 4 }).map((_, i) => (
          <div className="metric-tile" key={i}>
            <SkeletonLine width="40%" />
            <SkeletonLine width="60%" />
            <SkeletonLine width="80%" />
          </div>
        ))}
      </div>
    );
  }

  if (variant === 'inline') {
    return (
      <div className="skeleton-inline">
        <SkeletonLine width="120px" />
        <SkeletonLine width="80px" />
      </div>
    );
  }

  return (
    <div className="skeleton-list">
      {Array.from({ length: rows }).map((_, i) => (
        <div className="skeleton-row" key={i}>
          <SkeletonLine width="30%" />
          <SkeletonLine width="50%" />
          <SkeletonLine width="20%" />
        </div>
      ))}
    </div>
  );
}
