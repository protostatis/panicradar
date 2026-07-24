import { useEffect, useState } from 'react';

/**
 * useScrollFade — detect whether a horizontally-scrollable element overflows,
 * so an edge fade can be shown only when there's actually more to scroll to
 * (never misleading on wide viewports where everything fits).
 *
 * Returns { canScrollLeft, canScrollRight }.
 */
export const useScrollFade = (ref, deps = []) => {
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;

    const update = () => {
      const max = el.scrollWidth - el.clientWidth;
      setCanScrollLeft(el.scrollLeft > 1);
      setCanScrollRight(el.scrollLeft < max - 1);
    };
    update();
    el.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    return () => {
      el.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { canScrollLeft, canScrollRight };
};

export default useScrollFade;
