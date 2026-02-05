import { Link, useLocation } from 'react-router-dom';

const RadarIcon = ({ className = "w-10 h-10" }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Outer ring */}
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" className="text-green-400" />
    {/* Middle ring */}
    <circle cx="12" cy="12" r="6.5" stroke="currentColor" strokeWidth="1" className="text-green-400/70" />
    {/* Inner ring */}
    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1" className="text-green-400/50" />
    {/* Center dot */}
    <circle cx="12" cy="12" r="1.5" fill="currentColor" className="text-green-300" />
    {/* Sweep line */}
    <line x1="12" y1="12" x2="12" y2="2" stroke="url(#sweepGradient)" strokeWidth="2" strokeLinecap="round" />
    {/* Blip */}
    <circle cx="15" cy="7" r="1.5" fill="currentColor" className="text-red-500 animate-pulse" />
    <defs>
      <linearGradient id="sweepGradient" x1="12" y1="12" x2="12" y2="2" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stopColor="#4ade80" stopOpacity="0.2" />
        <stop offset="100%" stopColor="#4ade80" stopOpacity="1" />
      </linearGradient>
    </defs>
  </svg>
);

const Header = () => {
  const location = useLocation();

  const navItems = [
    { path: '/', label: 'Dashboard' },
    { path: '/beliefs', label: 'Beliefs' },
    { path: '/sources', label: 'Sources' },
    { path: '/blog', label: 'Blog' },
    { path: '/about', label: 'About' },
  ];

  return (
    <header className="bg-slate-900/80 backdrop-blur-sm border-b border-slate-800 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          <Link to="/" className="flex items-center gap-2">
            <RadarIcon className="w-10 h-10" />
            <span className="text-xl font-bold text-slate-100">
              PanicRadar.ai
            </span>
          </Link>
          <nav className="flex gap-1">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  location.pathname === item.path
                    ? 'bg-slate-700 text-slate-100'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
};

export default Header;
