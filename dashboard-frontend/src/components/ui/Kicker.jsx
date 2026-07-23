/**
 * Kicker — standardized section label. One tracking value, site-wide.
 * Use `tick` to add a status dot (like an instrument label).
 */
const Kicker = ({ children, tick = false, className = '', ...rest }) => (
  <span
    className={`radar-kicker ${tick ? 'radar-kicker--tick' : ''} ${className}`.trim()}
    {...rest}
  >
    {children}
  </span>
);

export default Kicker;
