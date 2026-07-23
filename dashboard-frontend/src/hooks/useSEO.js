import { useEffect } from 'react';

/**
 * Sets document title, meta description, and Open Graph tags dynamically.
 * Essential for SPA SEO since there's only one index.html.
 */
export default function useSEO({ title, description, url, type = 'website', image = 'https://panicradar.ai/og-image.png' }) {
  useEffect(() => {
    const suffix = ' | PanicRadar';

    // Title
    if (title) {
      document.title = title.includes('PanicRadar') ? title : title + suffix;
    }

    // Meta description
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc && description) {
      metaDesc.setAttribute('content', description);
    }

    // OG tags
    const ogTags = { 'og:title': title, 'og:description': description, 'og:url': url, 'og:type': type, 'og:image': image };
    for (const [property, content] of Object.entries(ogTags)) {
      if (!content) continue;
      let tag = document.querySelector(`meta[property="${property}"]`);
      if (tag) {
        tag.setAttribute('content', content);
      }
    }

    // Twitter tags
    const twitterTags = { 'twitter:title': title, 'twitter:description': description, 'twitter:image': image };
    for (const [name, content] of Object.entries(twitterTags)) {
      if (!content) continue;
      let tag = document.querySelector(`meta[name="${name}"]`);
      if (tag) {
        tag.setAttribute('content', content);
      }
    }

    // Canonical URL
    if (url) {
      let canonical = document.querySelector('link[rel="canonical"]');
      if (canonical) {
        canonical.setAttribute('href', url);
      }
    }
  }, [title, description, url, type, image]);
}
