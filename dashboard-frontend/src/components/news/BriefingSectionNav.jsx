import { useEffect, useRef, useState } from 'react';
import { useScrollFade } from '../ui/useScrollFade';

/**
 * BriefingSectionNav — sticky table-of-contents for the long daily briefing.
 * Tracks the section currently in view via IntersectionObserver and highlights
 * the active link, so readers always know where they are and can jump around.
 *
 * A scroll-aware right-edge fade appears only when the nav overflows (mobile),
 * so it never misleads on desktop where all items fit.
 *
 * Each item: { id, label, count? }
 */
const BriefingSectionNav = ({ items }) => {
  const [activeId, setActiveId] = useState(items[0]?.id || '');
  const scrollRef = useRef(null);
  const { canScrollRight } = useScrollFade(scrollRef, [items]);

  useEffect(() => {
    if (items.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the topmost intersecting section.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveId(visible[0].target.id);
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0 },
    );

    items.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <nav aria-label="Briefing sections" className="sticky top-16 z-30 -mx-1">
      <div className="relative">
        <div
          ref={scrollRef}
          className="radar-card flex items-center gap-1 overflow-x-auto p-1.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {items.map(({ id, label, count }) => {
            const active = activeId === id;
            return (
              <a
                key={id}
                href={`#${id}`}
                className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition-all active:scale-95 ${
                  active
                    ? 'bg-cyan-400/15 text-cyan-300 shadow-[0_0_18px_-6px_rgba(34,211,238,0.5)]'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
                aria-current={active ? 'true' : undefined}
              >
                {label}
                {count != null && (
                  <span className="ml-1.5 text-[0.65rem] text-slate-500">{count}</span>
                )}
              </a>
            );
          })}
        </div>
        {canScrollRight && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute right-0 top-0 h-full w-8 rounded-r-xl bg-gradient-to-l from-slate-900 via-slate-900/70 to-transparent"
          />
        )}
      </div>
    </nav>
  );
};

export default BriefingSectionNav;
