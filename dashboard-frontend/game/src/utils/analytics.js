let pageViewSent = false;

function enabled() {
  return window.__PANICRADAR_ENABLE_ANALYTICS__ && typeof window.gtag === 'function';
}

export function trackGamePageView() {
  if (pageViewSent || !enabled()) return;
  pageViewSent = true;
  window.gtag('event', 'page_view', {
    page_path: '/game/',
    page_location: 'https://panicradar.ai/game/',
    page_title: document.title,
  });
}

export function trackGameEvent(name, parameters = {}) {
  if (!enabled()) return;
  window.gtag('event', name, parameters);
}
