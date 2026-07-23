import Kicker from './Kicker';

/**
 * SectionHeader — consistent section heading block.
 * Groups a kicker, title, and optional description / right-side actions,
 * so every dashboard section has the same rhythm.
 */
const SectionHeader = ({
  kicker,
  kickerTick = false,
  title,
  description,
  actions,
  // eslint-disable-next-line no-unused-vars -- used in JSX below
  as: Tag = 'h2',
  className = '',
}) => (
  <div className={`flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between ${className}`.trim()}>
    <div className="min-w-0">
      {kicker && (
        <Kicker tick={kickerTick} className="mb-2">
          {kicker}
        </Kicker>
      )}
      <Tag className="font-display text-2xl font-semibold tracking-tight text-slate-50 sm:text-3xl">
        {title}
      </Tag>
      {description && (
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-400">
          {description}
        </p>
      )}
    </div>
    {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
  </div>
);

export default SectionHeader;
