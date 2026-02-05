import { useState, useEffect, useCallback } from 'react';
import { fetchRecentPosts } from '../api/client';

const formatTimeAgo = (dateStr) => {
  // Parse as UTC since the server returns UTC timestamps
  // Handle both "Z" suffix and "+00:00" offset formats
  const hasTimezone = dateStr.includes('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr);
  const date = new Date(hasTimezone ? dateStr : dateStr + 'Z');
  const now = new Date();
  const diffMs = now - date;
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
};

const formatSourceName = (source) => {
  return source
    .replace('reddit_', 'r/')
    .replace('4chan_', '/')
    .replace(/_/g, '');
};

const getSourceColor = (source) => {
  if (source.includes('bitcoin')) return 'text-orange-400';
  if (source.includes('ethereum')) return 'text-purple-400';
  if (source.includes('solana')) return 'text-green-400';
  if (source.includes('cryptocurrency')) return 'text-blue-400';
  if (source.includes('altcoin')) return 'text-yellow-400';
  if (source.includes('4chan')) return 'text-red-400';
  return 'text-slate-400';
};

const getSentimentColor = (score) => {
  if (score === null || score === undefined) return 'bg-slate-700/30';
  if (score >= 0.3) return 'bg-green-900/40 border-l-2 border-green-500';
  if (score >= 0.1) return 'bg-green-900/20';
  if (score <= -0.3) return 'bg-red-900/40 border-l-2 border-red-500';
  if (score <= -0.1) return 'bg-red-900/20';
  return 'bg-slate-700/30';
};

const getScoreTextColor = (score) => {
  if (score === null || score === undefined) return 'text-slate-500';
  if (score >= 0.1) return 'text-green-400';
  if (score <= -0.1) return 'text-red-400';
  return 'text-slate-500';
};

const CopyButton = ({ url }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e) => {
    e.stopPropagation();
    if (url) {
      try {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      } catch (err) {
        console.error('Failed to copy:', err);
      }
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={`p-1.5 rounded transition-colors ${
        copied
          ? 'bg-green-600 text-white'
          : 'bg-slate-600/50 text-slate-400 hover:bg-slate-600 hover:text-slate-200'
      }`}
      title={copied ? 'Copied!' : 'Copy link'}
    >
      {copied ? (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      ) : (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      )}
    </button>
  );
};

const PostCard = ({ post }) => {
  const [expanded, setExpanded] = useState(false);
  const hasContent = post.content && post.content.length > 0;
  const truncatedContent = post.content?.slice(0, 200);
  const needsTruncation = post.content && post.content.length > 200;

  const handleClick = () => {
    if (post.url) {
      window.open(post.url, '_blank', 'noopener,noreferrer');
    }
  };

  const handleExpandClick = (e) => {
    e.stopPropagation();
    setExpanded(!expanded);
  };

  return (
    <div
      className={`${getSentimentColor(post.score)} rounded-lg p-3 hover:brightness-110 transition-all ${post.url ? 'cursor-pointer' : ''}`}
      onClick={handleClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-xs font-medium ${getSourceColor(post.source)}`}>
              {formatSourceName(post.source)}
            </span>
            <span className="text-xs text-slate-500">
              {formatTimeAgo(post.created_at)}
            </span>
            {post.score !== null && post.score !== undefined && (
              <span className={`text-xs font-medium ${getScoreTextColor(post.score)}`}>
                {post.score > 0 ? '+' : ''}{post.score.toFixed(2)}
              </span>
            )}
          </div>
          <h4 className="text-sm text-slate-200 font-medium leading-tight">
            {post.title}
          </h4>
          {hasContent && (
            <div className="mt-2">
              <p className="text-xs text-slate-400 leading-relaxed">
                {expanded ? post.content : truncatedContent}
                {needsTruncation && !expanded && '...'}
              </p>
              {needsTruncation && (
                <button
                  onClick={handleExpandClick}
                  className="text-xs text-purple-400 hover:text-purple-300 mt-1"
                >
                  {expanded ? 'Show less' : 'Read more'}
                </button>
              )}
            </div>
          )}
        </div>
        {post.url && (
          <div className="flex-shrink-0">
            <CopyButton url={post.url} />
          </div>
        )}
      </div>
    </div>
  );
};

const RecentPostsFeed = () => {
  const [posts, setPosts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedSource, setSelectedSource] = useState(null);

  const loadPosts = useCallback(async () => {
    try {
      const data = await fetchRecentPosts(15, selectedSource);
      setPosts(data.posts);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      console.error('Failed to load posts:', err);
      setError('Failed to load posts');
    } finally {
      setLoading(false);
    }
  }, [selectedSource]);

  useEffect(() => {
    loadPosts();
    // Refresh every 30 seconds
    const interval = setInterval(loadPosts, 30000);
    return () => clearInterval(interval);
  }, [loadPosts]);

  const sources = [
    { value: null, label: 'All Sources' },
    { value: 'reddit_bitcoin', label: 'r/bitcoin' },
    { value: 'reddit_cryptocurrency', label: 'r/cryptocurrency' },
    { value: 'reddit_ethereum', label: 'r/ethereum' },
    { value: 'reddit_solana', label: 'r/solana' },
  ];

  return (
    <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4 h-[520px] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold text-slate-200">Live Feed</h3>
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedSource || ''}
            onChange={(e) => setSelectedSource(e.target.value || null)}
            className="bg-slate-700 border border-slate-600 text-slate-200 text-xs rounded-lg px-2 py-1 focus:ring-purple-500 focus:border-purple-500"
          >
            {sources.map((s) => (
              <option key={s.value || 'all'} value={s.value || ''}>
                {s.label}
              </option>
            ))}
          </select>
          <span className="text-xs text-slate-500">
            {total.toLocaleString()} total
          </span>
        </div>
      </div>

      {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="bg-slate-700/30 rounded-lg p-3 animate-pulse">
              <div className="h-3 bg-slate-600 rounded w-1/4 mb-2"></div>
              <div className="h-4 bg-slate-600 rounded w-3/4"></div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="text-center py-8 text-slate-500">{error}</div>
      ) : posts.length === 0 ? (
        <div className="text-center py-8 text-slate-500">No posts found</div>
      ) : (
        <div className="space-y-2 flex-1 overflow-y-auto pr-1">
          {posts.map((post) => (
            <PostCard key={post.id} post={post} />
          ))}
        </div>
      )}
    </div>
  );
};

export default RecentPostsFeed;
