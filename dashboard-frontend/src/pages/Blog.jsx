import { Link } from 'react-router-dom';
import useSEO from '../hooks/useSEO';

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
    <div className="space-y-8 max-w-3xl">
      <header>
        <h1 className="text-3xl font-bold text-slate-100">
          Crypto Sentiment Research & Insights
        </h1>
        <p className="mt-2 text-slate-400 leading-relaxed">
          Data-driven research on crypto market sentiment, Bayesian source
          analysis, and contrarian signal detection. We publish what we learn
          building PanicRadar — including what doesn't work.
        </p>
      </header>

      <div className="grid gap-6">
        {blogPosts.map((post) => (
          <article key={post.slug}>
            <Link
              to={`/blog/${post.slug}`}
              className="block bg-slate-800/50 rounded-xl p-6 border border-slate-700 hover:border-purple-500/50 hover:bg-slate-800/70 transition-all"
            >
              <div className="flex items-center gap-3 mb-3">
                <span className="px-2 py-1 text-xs font-medium bg-purple-500/20 text-purple-300 rounded">
                  {post.category}
                </span>
                <time dateTime={post.date} className="text-sm text-slate-500">
                  {post.date}
                </time>
                <span className="text-sm text-slate-500">
                  {post.readingTime} read
                </span>
              </div>
              <h2 className="text-xl font-semibold text-slate-100 mb-2">
                {post.title}
              </h2>
              <p className="text-slate-400 leading-relaxed">{post.excerpt}</p>
              <span className="inline-block mt-4 text-purple-400 text-sm font-medium">
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
