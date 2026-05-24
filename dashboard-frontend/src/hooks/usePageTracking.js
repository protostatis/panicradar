import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export default function usePageTracking() {
  const location = useLocation();

  useEffect(() => {
    if (window.__PANICRADAR_ENABLE_ANALYTICS__ && typeof window.gtag === 'function') {
      const normalizedPath = location.pathname.length > 1
        ? location.pathname.replace(/\/+$/, '')
        : location.pathname;
      const pagePath = `${normalizedPath}${location.search}`;

      window.gtag('event', 'page_view', {
        page_path: pagePath,
        page_location: `${window.location.origin}${pagePath}${location.hash}`,
        page_title: document.title,
      });
    }
  }, [location]);
}
