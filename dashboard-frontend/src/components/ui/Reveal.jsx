import { useEffect, useRef, useState } from 'react';

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Reveal — fades + slides children into view when they enter the viewport.
 * One-shot (reveals once, then stops observing). Respects prefers-reduced-motion
 * by rendering immediately with no transform.
 *
 * props:
 *  - delay: ms stagger (for sequencing sibling items)
 *  - as: element type (default 'div')
 *  - y: translate distance before reveal (default 16px)
 */
const Reveal = ({
  children,
  delay = 0,
  // eslint-disable-next-line no-unused-vars -- used in JSX below
  as: Tag = 'div',
  y = 16,
  className = '',
  ...rest
}) => {
  const ref = useRef(null);
  const [shown, setShown] = useState(prefersReducedMotion());

  useEffect(() => {
    if (shown) return undefined;
    const el = ref.current;
    if (!el) return undefined;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { threshold: 0.08, rootMargin: '0px 0px -8% 0px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [shown]);

  const style = shown
    ? undefined
    : { opacity: 0, transform: `translateY(${y}px)`, transitionDelay: `${delay}ms` };

  return (
    <Tag
      ref={ref}
      className={`${className} transition-[opacity,transform] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] will-change-[opacity,transform]`}
      style={style}
      {...rest}
    >
      {children}
    </Tag>
  );
};

export default Reveal;
