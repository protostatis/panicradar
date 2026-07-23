import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

const RadarIcon = ({ className = "w-10 h-10" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Outer ring */}
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" className="text-cyan-400/60" />
    {/* Middle ring */}
    <circle cx="12" cy="12" r="6.5" stroke="currentColor" strokeWidth="1" className="text-cyan-400/45" />
    {/* Inner ring */}
    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1" className="text-cyan-400/30" />
    {/* Center dot */}
    <circle cx="12" cy="12" r="1.5" fill="currentColor" className="text-cyan-300" />
    {/* Sweep line */}
    <line x1="12" y1="12" x2="12" y2="2" stroke="url(#sweepGradient)" strokeWidth="2" strokeLinecap="round" />
    {/* Blip */}
    <circle cx="15" cy="7" r="1.5" fill="currentColor" className="text-rose-400 animate-pulse" />
    <defs>
      <linearGradient id="sweepGradient" x1="12" y1="12" x2="12" y2="2" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.2" />
        <stop offset="100%" stopColor="#22d3ee" stopOpacity="1" />
      </linearGradient>
    </defs>
  </svg>
);

const Header = () => {
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navItems = [
    { path: '/game/', label: 'Game', standalone: true },
    { path: '/news', label: 'News' },
    { path: '/dashboard', label: 'Dashboard' },
    { path: '/beliefs', label: 'Beliefs' },
    { path: '/sources', label: 'Sources' },
    { path: '/blog', label: 'Blog' },
    { path: '/about', label: 'About' },
  ];

  return (
    <header className="radar-header sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          <Link to="/" className="flex items-center gap-2">
            <RadarIcon className="w-10 h-10" />
            <span className="font-display text-xl font-semibold tracking-tight text-slate-100">
              PanicRadar<span className="text-cyan-400">.ai</span>
            </span>
          </Link>

          {/* Desktop nav */}
          <nav className="hidden md:flex gap-0.5 lg:gap-1">
            {navItems.map((item) => {
              const className = `px-2.5 lg:px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                location.pathname === item.path
                  ? 'bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/25'
                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/70'
              }`;

              return item.standalone ? (
                <a key={item.path} href={item.path} className={className}>
                  {item.label}
                </a>
              ) : (
                <Link key={item.path} to={item.path} className={className}>
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* Mobile hamburger button */}
          <button
            className="md:hidden p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle menu"
            aria-expanded={mobileMenuOpen}
          >
            {mobileMenuOpen ? (
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            ) : (
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {mobileMenuOpen && (
        <nav className="md:hidden border-t border-slate-800 bg-slate-950/95 backdrop-blur-sm">
          <div className="px-4 py-3 space-y-1">
            {navItems.map((item) => {
              const className = `block px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
                location.pathname === item.path
                  ? 'bg-cyan-400/10 text-cyan-100 ring-1 ring-cyan-300/25'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`;

              return item.standalone ? (
                <a key={item.path} href={item.path} className={className}>
                  {item.label}
                </a>
              ) : (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setMobileMenuOpen(false)}
                  className={className}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        </nav>
      )}
    </header>
  );
};

export default Header;
