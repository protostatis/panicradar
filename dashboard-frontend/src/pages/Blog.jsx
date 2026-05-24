import { Link } from 'react-router-dom';
import useSEO from '../hooks/useSEO';
import { trackEvent, GA_EVENTS } from '../utils/analytics';

const blogPosts = [
  {
    slug: 'gp-beta-correlated-sampling',
    title: 'Teaching Our Crawler That r/Bitcoin and r/CryptoCurrency Are Related',
    date: '2026-02-07',
    excerpt: 'We built a Gaussian Process model that lets our Bayesian crawler share knowledge between similar Reddit sources. When r/bitcoin proves accurate, r/cryptocurrency\'s beliefs improve too. Here\'s the math behind correlated Thompson Sampling.',
    category: 'Research',
    readingTime: '12 min',
  },
  {
    slug: 'looking-for-partners',
    title: 'Looking for Affiliate Partners',
    date: '2026-02-04',
    excerpt: 'PanicRadar.ai is seeking affiliate partners to help grow our crypto sentiment intelligence platform. Learn about our partnership program and how you can earn commissions.',
    category: 'Announcement',
    readingTime: '3 min',
  },
  {
    slug: 'causal-analysis-findings',
    title: 'What We Learned: Does Reddit Sentiment Actually Move Crypto Prices?',
    date: '2026-02-04',
    excerpt: 'We ran a rigorous causal analysis to find out if social media sentiment predicts crypto price movements. The answer surprised us — price leads sentiment by ~15 hours, not the other way around.',
    category: 'Research',
    readingTime: '8 min',
  },
];

const Blog = () => {
  useSEO({
    title: 'Blog — Crypto Sentiment Research & Analysis',
    description:
      'Research findings on crypto sentiment analysis, Bayesian source weighting, and contrarian signal detection. Data-driven insights from PanicRadar.',
    url: 'https://panicradar.ai/blog',
  });

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      <header className="radar-panel p-6 sm:p-8">
        <div className="radar-kicker mb-3">Research Log</div>
        <h1 className="max-w-3xl text-3xl font-bold text-slate-100 sm:text-4xl">
          Crypto Sentiment Research & Insights
        </h1>
        <p className="mt-3 max-w-3xl text-slate-400 leading-relaxed">
          Data-driven research on crypto market sentiment, Bayesian source
          analysis, and contrarian signal detection. We publish what we learn
          building PanicRadar — including what doesn't work.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        {blogPosts.map((post) => (
          <article key={post.slug}>
            <Link
              to={`/blog/${post.slug}`}
              onClick={() => trackEvent(GA_EVENTS.BLOG_ARTICLE_CLICK, { label: post.slug, title: post.title })}
                className="radar-panel block h-full p-6 transition-all hover:-translate-y-0.5 hover:border-emerald-400/40"
            >
              <div className="flex items-center gap-3 mb-3">
                  <span className="radar-chip px-2 py-1 text-xs font-medium text-emerald-300">
                  {post.category}
                </span>
                <time dateTime={post.date} className="text-sm text-slate-500">
                  {post.date}
                </time>
                <span className="text-sm text-slate-500">
                  {post.readingTime} read
                </span>
              </div>
              <h2 className="text-xl font-semibold text-slate-100 mb-2 leading-snug">
                {post.title}
              </h2>
              <p className="text-slate-400 leading-relaxed">{post.excerpt}</p>
              <span className="inline-block mt-4 text-emerald-300 text-sm font-medium">
                Read more &rarr;
              </span>
            </Link>
          </article>
        ))}
      </div>
    </div>
  );
};

export default Blog;
