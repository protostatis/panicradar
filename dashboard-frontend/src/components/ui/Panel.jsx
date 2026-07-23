import { forwardRef } from 'react';

/**
 * Panel — the single unified surface used across the app.
 * Replaces the 4 different "panel/card" implementations.
 *
 * props:
 *  - accent: true  -> top hairline accent (the "instrument" cue)
 *  - as: element/card variant ('panel' | 'card')
 *  - pad: padding token ('none'|'sm'|'md'|'lg')
 */
const PAD = {
  none: '',
  sm: 'p-4',
  md: 'p-5 sm:p-6',
  lg: 'p-6 sm:p-8',
};

const Panel = forwardRef(function Panel(
  { as = 'panel', accent = false, pad = 'md', className = '', children, ...rest },
  ref,
) {
  const base = as === 'card' ? 'radar-card' : 'radar-panel';
  const accentCls = accent ? 'radar-panel--accent' : '';
  return (
    <div ref={ref} className={`${base} ${accentCls} ${PAD[pad] || ''} ${className}`.trim()} {...rest}>
      {children}
    </div>
  );
});

export default Panel;
