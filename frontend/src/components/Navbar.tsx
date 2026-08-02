import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Sparkles, LogOut, User as UserIcon, Library as LibraryIcon, Upload, Images } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;

  return (
    <header className="relative z-10 border-b border-slate-800/80 bg-slate-950/60 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-20 flex items-center justify-between">
        <div className="flex items-center space-x-6 sm:space-x-8">
          <Link to="/" className="flex items-center space-x-3 group">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-rose-500 to-purple-600 flex items-center justify-center shadow-lg shadow-amber-500/20 group-hover:scale-105 transition-transform">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-2xl tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              Muse
            </span>
          </Link>

          {/* Nav Links */}
          <nav className="flex items-center space-x-1">
            <Link
              to="/library"
              className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition ${
                isActive('/library')
                  ? 'bg-slate-900 text-amber-400 border border-slate-800'
                  : 'text-slate-300 hover:text-white hover:bg-slate-900/50'
              }`}
            >
              <LibraryIcon className="w-4 h-4" />
              <span>Library</span>
            </Link>

            <Link
              to="/upload"
              className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition ${
                isActive('/upload')
                  ? 'bg-slate-900 text-amber-400 border border-slate-800'
                  : 'text-slate-300 hover:text-white hover:bg-slate-900/50'
              }`}
            >
              <Upload className="w-4 h-4" />
              <span>Upload</span>
            </Link>

            {user && (
              <Link
                to="/gallery"
                className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition ${
                  isActive('/gallery')
                    ? 'bg-slate-900 text-amber-400 border border-slate-800'
                    : 'text-slate-300 hover:text-white hover:bg-slate-900/50'
                }`}
              >
                <Images className="w-4 h-4" />
                <span>Gallery</span>
              </Link>
            )}
          </nav>
        </div>

        <div className="flex items-center space-x-4">
          {user ? (
            <div className="flex items-center space-x-3">
              <div className="hidden sm:flex items-center space-x-2 text-sm text-slate-300 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg">
                <UserIcon className="w-4 h-4 text-amber-400" />
                <span>{user.name || user.email}</span>
              </div>
              <button
                onClick={logout}
                className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-rose-400 hover:border-rose-900/50 transition"
                title="Log out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <div className="flex items-center space-x-3">
              <Link
                to="/login"
                className="px-4 py-2 text-sm font-medium text-slate-300 hover:text-white transition"
              >
                Log in
              </Link>
              <Link
                to="/register"
                className="px-4 py-2 text-sm font-medium bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold rounded-lg shadow-md shadow-amber-500/10 transition"
              >
                Sign up
              </Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
