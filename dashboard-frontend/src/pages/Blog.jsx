import { Link } from 'react-router-dom';

const blogPosts = [
  {
    slug: 'looking-for-partners',
    title: 'Looking for Affiliate Partners',
    date: '2026-02-04',
    excerpt: 'PanicRadar.ai is seeking affiliate partners to help grow our crypto sentiment intelligence platform. Learn about our partnership program and how you can earn commissions.',
    category: 'Announcement',
  },
  {
    slug: 'causal-analysis-findings',
    title: 'What We Learned: Does Reddit Sentiment Actually Move Crypto Prices?',
    date: '2026-02-04',
    excerpt: 'We ran a rigorous causal analysis to find out if social media sentiment predicts crypto price movements. The answer surprised us - and changed how we built our signals.',
    category: 'Research',
  },
];

const Blog = () => {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-100">Blog</h1>
        <p className="mt-2 text-slate-400">
          Updates, research findings, and announcements from the PanicRadar.ai team.
        </p>
      </div>

      <div className="grid gap-6">
        {blogPosts.map((post) => (
          <Link
            key={post.slug}
            to={`/blog/${post.slug}`}
            className="block bg-slate-800/50 rounded-xl p-6 border border-slate-700 hover:border-purple-500/50 hover:bg-slate-800/70 transition-all"
          >
            <div className="flex items-center gap-3 mb-3">
              <span className="px-2 py-1 text-xs font-medium bg-purple-500/20 text-purple-300 rounded">
                {post.category}
              </span>
              <span className="text-sm text-slate-500">{post.date}</span>
            </div>
            <h2 className="text-xl font-semibold text-slate-100 mb-2">
              {post.title}
            </h2>
            <p className="text-slate-400 leading-relaxed">
              {post.excerpt}
            </p>
            <span className="inline-block mt-4 text-purple-400 text-sm font-medium">
              Read more &rarr;
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
};

export default Blog;
