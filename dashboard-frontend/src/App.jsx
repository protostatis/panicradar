import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import Dashboard from './pages/Dashboard';
import Beliefs from './pages/Beliefs';
import Sources from './pages/Sources';
import About from './pages/About';

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-slate-900 text-slate-100">
        <Header />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/beliefs" element={<Beliefs />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </main>
        <footer className="border-t border-slate-800 py-6 mt-12">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-slate-500 text-sm">
            <p>Panic Radar &mdash; Crypto Sentiment Analysis</p>
            <p className="mt-1">Data updated hourly. Not financial advice.</p>
          </div>
        </footer>
      </div>
    </Router>
  );
}

export default App;
