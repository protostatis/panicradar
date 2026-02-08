import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import Landing from './pages/Landing';
import Dashboard from './pages/Dashboard';
import Beliefs from './pages/Beliefs';
import Sources from './pages/Sources';
import Blog from './pages/Blog';
import BlogPost from './pages/BlogPost';
import About from './pages/About';
import usePageTracking from './hooks/usePageTracking';

function AppContent() {
  usePageTracking();

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <Header />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/beliefs" element={<Beliefs />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/blog" element={<Blog />} />
            <Route path="/blog/:slug" element={<BlogPost />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </main>
        <footer className="border-t border-slate-800 py-6 mt-12">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-slate-500 text-sm">
            <p>PanicRadar.ai &mdash; Crypto Sentiment Analysis</p>
            <p className="mt-1">Data updated hourly. Not financial advice.</p>
            <div className="flex items-center justify-center gap-4 mt-3">
              <a
                href="https://t.me/PanicRadarAlerts"
                target="_blank"
                rel="noopener noreferrer"
                className="text-purple-400 hover:text-purple-300 transition-colors"
              >
                Telegram
              </a>
              <span className="text-slate-700">&middot;</span>
              <a
                href="https://panicradar.substack.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-purple-400 hover:text-purple-300 transition-colors"
              >
                Newsletter
              </a>
              <span className="text-slate-700">&middot;</span>
              <a
                href="https://x.com/PanicRadar_AI"
                target="_blank"
                rel="noopener noreferrer"
                className="text-purple-400 hover:text-purple-300 transition-colors"
              >
                Twitter/X
              </a>
              <span className="text-slate-700">&middot;</span>
              <a
                href="mailto:protostatis.dev@gmail.com?subject=Affiliate%20Partnership%20Inquiry%20-%20PanicRadar.ai&body=Hi%20PanicRadar.ai%20Team%2C%0A%0AI'm%20interested%20in%20becoming%20an%20affiliate%20partner.%0A%0ACompany%2FName%3A%20%0AWebsite%3A%20%0AHow%20I%20plan%20to%20promote%3A%20%0A%0AThanks!"
                className="text-purple-400 hover:text-purple-300 transition-colors"
              >
                Become a Partner
              </a>
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
