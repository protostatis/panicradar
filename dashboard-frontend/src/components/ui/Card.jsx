import { forwardRef } from 'react';

const PAD = { none: '', sm: 'p-4', md: 'p-5', lg: 'p-6' };

/**
 * Card — the lighter surface (raised tile / list item).
 * Use Panel for primary sections, Card for nested tiles.
 */
const Card = forwardRef(function Card(
  { pad = 'md', className = '', children, ...rest },
  ref,
) {
  return (
    <div ref={ref} className={`radar-card ${PAD[pad] || ''} ${className}`.trim()} {...rest}>
      {children}
    </div>
  );
});

export default Card;
