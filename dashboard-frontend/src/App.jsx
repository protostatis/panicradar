import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import Beliefs from './pages/Beliefs';
import Sources from './pages/Sources';
import Blog from './pages/Blog';
import BlogPost from './pages/BlogPost';
import About from './pages/About';
import News from './pages/News';
import usePageTracking from './hooks/usePageTracking';

function AppContent() {
  usePageTracking();

  return (
    <div className="radar-site min-h-screen text-slate-100">
      <Header />
        <main className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/news" element={<News />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/beliefs" element={<Beliefs />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/blog" element={<Blog />} />
            <Route path="/blog/:slug" element={<BlogPost />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </main>
        <footer className="radar-footer relative z-10 py-10 mt-16">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex flex-col items-center gap-4 text-center sm:flex-row sm:justify-between sm:text-left">
              <div>
                <div className="font-display text-base font-semibold text-slate-200">
                  PanicRadar<span className="text-cyan-400">.ai</span>
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  Crypto crowd-risk intelligence. Data updated continuously — not financial advice.
                </p>
              </div>
              <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm">
                <a href="https://t.me/PanicRadarAlerts" target="_blank" rel="noopener noreferrer" className="text-slate-400 transition-colors hover:text-cyan-300">Telegram</a>
                <span className="text-slate-700">&middot;</span>
                <a href="https://panicradar.substack.com" target="_blank" rel="noopener noreferrer" className="text-slate-400 transition-colors hover:text-cyan-300">Newsletter</a>
                <span className="text-slate-700">&middot;</span>
                <a href="https://x.com/PanicRadar_AI" target="_blank" rel="noopener noreferrer" className="text-slate-400 transition-colors hover:text-cyan-300">Twitter/X</a>
                <span className="text-slate-700">&middot;</span>
                <a href="mailto:protostatis.dev@gmail.com?subject=Affiliate%20Partnership%20Inquiry%20-%20PanicRadar.ai&body=Hi%20PanicRadar.ai%20Team%2C%0A%0AI'm%20interested%20in%20becoming%20an%20affiliate%20partner.%0A%0ACompany%2FName%3A%20%0AWebsite%3A%20%0AHow%20I%20plan%20to%20promote%3A%20%0A%0AThanks!" className="text-slate-400 transition-colors hover:text-cyan-300">Become a Partner</a>
              </div>
            </div>
          </div>
        </footer>
      </div>
  );
}

function App() {
  return (
    <Router>
      <AppContent />
    </Router>
  );
}

export default App;
