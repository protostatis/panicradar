import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { join } from 'path';

/**
 * Lightweight Vite plugin that generates per-route HTML files at build time
 * with correct <title>, meta description, OG tags, Twitter Cards, and canonical URLs.
 *
 * This solves the SPA SEO problem: crawlers and social media scrapers get
 * route-specific meta tags without needing to execute JavaScript.
 *
 * Zero external dependencies — just copies dist/index.html and swaps meta tags.
 */

const routes = [
  {
    path: '/',
    title: 'PanicRadar — Crypto Panic Early Warning System',
    description:
      'Real-time contrarian signals from 30+ crypto communities. Bayesian intelligence detects when extreme fear means opportunity. Free alerts.',
    url: 'https://panicradar.ai',
    ogTitle: 'PanicRadar — See the panic before the crowd.',
  },
  {
    path: '/dashboard',
    title: 'Live Crypto Sentiment Dashboard — PanicRadar',
    description:
      'Real-time crypto sentiment dashboard with panic scores, source weights, and contrarian signals from 30+ communities.',
    url: 'https://panicradar.ai/dashboard',
    ogTitle: 'Live Crypto Sentiment Dashboard | PanicRadar',
  },
  {
    path: '/beliefs',
    title: 'Bayesian Beliefs — PanicRadar',
    description:
      "See how PanicRadar's Bayesian system weights each crypto sentiment source. Thompson Sampling learns which communities predict price movements.",
    url: 'https://panicradar.ai/beliefs',
    ogTitle: 'Bayesian Source Beliefs | PanicRadar',
  },
  {
    path: '/sources',
    title: 'Source Intelligence — PanicRadar',
    description:
      'Explore 30+ crypto sentiment sources ranked by Bayesian accuracy. See which communities are momentum vs contrarian indicators.',
    url: 'https://panicradar.ai/sources',
    ogTitle: 'Crypto Sentiment Source Rankings | PanicRadar',
  },
  {
    path: '/blog',
    title: 'Blog — Crypto Sentiment Research & Analysis | PanicRadar',
    description:
      'Research findings on crypto sentiment analysis, Bayesian source weighting, and contrarian signal detection. Data-driven insights from PanicRadar.',
    url: 'https://panicradar.ai/blog',
    ogTitle: 'Crypto Sentiment Research & Insights | PanicRadar',
  },
  {
    path: '/blog/gp-beta-correlated-sampling',
    title:
      'Teaching Our Crawler That r/Bitcoin and r/CryptoCurrency Are Related | PanicRadar',
    description:
      'How we built a Gaussian Process model that shares knowledge between correlated Reddit sources, enabling correlated Thompson Sampling for smarter crawl decisions.',
    url: 'https://panicradar.ai/blog/gp-beta-correlated-sampling',
    ogTitle:
      'Teaching Our Crawler That r/Bitcoin and r/CryptoCurrency Are Related',
    type: 'article',
  },
  {
    path: '/blog/looking-for-partners',
    title: 'Looking for Affiliate Partners | PanicRadar',
    description:
      'PanicRadar.ai is seeking affiliate partners to help grow our crypto sentiment intelligence platform. Learn about our partnership program.',
    url: 'https://panicradar.ai/blog/looking-for-partners',
    ogTitle: 'Looking for Affiliate Partners | PanicRadar',
    type: 'article',
  },
  {
    path: '/blog/causal-analysis-findings',
    title:
      'What We Learned: Does Reddit Sentiment Actually Move Crypto Prices? | PanicRadar',
    description:
      'Granger causality analysis reveals price leads crypto sentiment by ~15 hours. We explain what this means for traders and how PanicRadar uses contrarian signals.',
    url: 'https://panicradar.ai/blog/causal-analysis-findings',
    ogTitle: 'Does Reddit Sentiment Actually Move Crypto Prices?',
    type: 'article',
  },
  {
    path: '/about',
    title: 'About PanicRadar — Crypto Sentiment Intelligence',
    description:
      'PanicRadar uses Bayesian intelligence and FinBERT NLP to detect contrarian crypto signals from 30+ communities. Learn about our methodology.',
    url: 'https://panicradar.ai/about',
    ogTitle: 'About PanicRadar | Crypto Sentiment Intelligence',
  },
];

function replaceMeta(html, route) {
  let result = html;

  // Title
  result = result.replace(
    /<title>[^<]*<\/title>/,
    `<title>${route.title}</title>`,
  );

  // Meta description
  result = result.replace(
    /<meta name="description" content="[^"]*"/,
    `<meta name="description" content="${route.description}"`,
  );

  // OG tags
  result = result.replace(
    /<meta property="og:url" content="[^"]*"/,
    `<meta property="og:url" content="${route.url}"`,
  );
  result = result.replace(
    /<meta property="og:title" content="[^"]*"/,
    `<meta property="og:title" content="${route.ogTitle || route.title}"`,
  );
  result = result.replace(
    /<meta property="og:description" content="[^"]*"/,
    `<meta property="og:description" content="${route.description}"`,
  );
  if (route.type) {
    result = result.replace(
      /<meta property="og:type" content="[^"]*"/,
      `<meta property="og:type" content="${route.type}"`,
    );
  }

  // Twitter Card tags
  result = result.replace(
    /<meta name="twitter:title" content="[^"]*"/,
    `<meta name="twitter:title" content="${route.ogTitle || route.title}"`,
  );
  result = result.replace(
    /<meta name="twitter:description" content="[^"]*"/,
    `<meta name="twitter:description" content="${route.description}"`,
  );

  // OG image (ensure it's set for all routes)
  if (!result.includes('og:image')) {
    result = result.replace(
      '</head>',
      '    <meta property="og:image" content="https://panicradar.ai/og-image.png" />\n    <meta property="og:image:width" content="1200" />\n    <meta property="og:image:height" content="630" />\n  </head>',
    );
  }
  if (!result.includes('twitter:image')) {
    result = result.replace(
      '</head>',
      '    <meta name="twitter:image" content="https://panicradar.ai/og-image.png" />\n  </head>',
    );
  }

  // Canonical URL
  result = result.replace(
    /<link rel="canonical" href="[^"]*"/,
    `<link rel="canonical" href="${route.url}"`,
  );

  return result;
}

export default function seoPrerender() {
  return {
    name: 'seo-prerender',
    closeBundle() {
      const distDir = join(process.cwd(), 'dist');
      let template;
      try {
        template = readFileSync(join(distDir, 'index.html'), 'utf-8');
      } catch {
        console.warn('[seo-prerender] No dist/index.html found, skipping.');
        return;
      }

      let count = 0;
      for (const route of routes) {
        const html = replaceMeta(template, route);

        if (route.path === '/') {
          // Overwrite root index.html with correct meta
          writeFileSync(join(distDir, 'index.html'), html);
        } else {
          const dir = join(distDir, route.path);
          mkdirSync(dir, { recursive: true });
          writeFileSync(join(dir, 'index.html'), html);
        }
        count++;
      }

      console.log(
        `[seo-prerender] Generated ${count} pre-rendered HTML files with route-specific meta tags.`,
      );
    },
  };
}
