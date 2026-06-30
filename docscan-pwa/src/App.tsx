import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import NavBar from './components/NavBar';
import ScanPage from './pages/ScanPage';
import ReviewPage from './pages/ReviewPage';
import DashboardPage from './pages/DashboardPage';
import FilesPage from './pages/FilesPage';
import FileDetailPage from './pages/FileDetailPage';
import SearchPage from './pages/SearchPage';
import ChatPage from './pages/ChatPage';
import JobsPage from './pages/JobsPage';
import SettingsPage from './pages/SettingsPage';

function Layout() {
  const { pathname } = useLocation();
  const fullscreen = pathname.startsWith('/scan');

  return (
    <div className="min-h-screen bg-slate-900 text-white flex flex-col">
      <Routes>
        <Route path="/scan" element={<ScanPage />} />
        <Route path="/scan/review" element={<ReviewPage />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/files" element={<FilesPage />} />
        <Route path="/files/:id" element={<FileDetailPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
      {!fullscreen && <NavBar />}
    </div>
  );
}

export default function App() {
  return <Layout />;
}
