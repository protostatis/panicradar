/**
 * State components — loading / empty / error / partial.
 * First-class, used everywhere so every async surface behaves consistently.
 */

export const LoadingState = ({ message = 'Loading…', rows = 3, className = '' }) => (
  <div
    className={`radar-card p-6 ${className}`.trim()}
    role="status"
    aria-live="polite"
    aria-busy="true"
  >
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-8 w-8 shrink-0 animate-pulse rounded-lg bg-slate-700/60" />
          <div className="flex-1 space-y-2">
            <div className="h-3 w-1/3 animate-pulse rounded bg-slate-700/60" />
            <div className="h-3 w-2/3 animate-pulse rounded bg-slate-700/40" />
          </div>
        </div>
      ))}
    </div>
    <p className="mt-4 text-sm text-slate-500">{message}</p>
  </div>
);

export const EmptyState = ({
  title = 'Nothing here yet',
  message,
  icon = '\u2014',
  action,
  className = '',
}) => (
  <div className={`radar-card flex flex-col items-center justify-center p-10 text-center ${className}`.trim()}>
    <div aria-hidden="true" className="mb-3 text-2xl text-slate-600">{icon}</div>
    <h3 className="text-sm font-semibold text-slate-300">{title}</h3>
    {message && <p className="mt-1 max-w-sm text-sm text-slate-500">{message}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

export const ErrorState = ({ message = 'Something went wrong.', onRetry, className = '' }) => (
  <div
    className={`radar-card flex flex-col items-center justify-center p-10 text-center ${className}`.trim()}
    role="alert"
  >
    <div
      aria-hidden="true"
      className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-red-400/40 bg-red-400/10 text-lg text-red-300"
    >
      !
    </div>
    <h3 className="text-sm font-semibold text-slate-200">Failed to load</h3>
    <p className="mt-1 max-w-sm text-sm text-slate-500">{message}</p>
    {onRetry && (
      <button onClick={onRetry} className="radar-button-ghost mt-4 px-4 py-2 text-sm">
        Try again
      </button>
    )}
  </div>
);

export default { LoadingState, EmptyState, ErrorState };
