import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Sparkles, LogOut, User as UserIcon, Library as LibraryIcon, Upload, Images } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

interface NavItem {
  to: string;
  label: string;
  icon: React.ElementType;
  authOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: '/library', label: 'Library', icon: LibraryIcon },
  { to: '/upload', label: 'Upload', icon: Upload },
  { to: '/gallery', label: 'Gallery', icon: Images, authOnly: true },
];

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const location = useLocation();

  const isActive = (path: string) => location.pathname === path;
  const items = NAV_ITEMS.filter((item) => !item.authOnly || user);

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 sm:h-20 flex items-center justify-between gap-3">
        <div className="flex items-center gap-4 sm:gap-8 min-w-0">
          <Link to="/" className="flex items-center gap-2.5 group flex-shrink-0">
            <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-gradient-to-tr from-amber-500 via-rose-500 to-purple-600 flex items-center justify-center shadow-lg shadow-amber-500/20 group-hover:scale-105 transition-transform">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <span className="font-bold text-xl sm:text-2xl tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              Muse
            </span>
          </Link>

          {/* Labels collapse to icons on narrow screens — the old markup kept
              them at full width and overflowed the header on a phone. */}
          <nav className="flex items-center gap-1" aria-label="Main">
            {items.map(({ to, label, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                aria-current={isActive(to) ? 'page' : undefined}
                title={label}
                className={`flex items-center gap-2 px-2.5 sm:px-3 py-2 rounded-lg text-sm font-medium transition ${
                  isActive(to)
                    ? 'bg-slate-900 text-amber-400 border border-slate-800'
                    : 'text-slate-300 hover:text-white hover:bg-slate-900/50 border border-transparent'
                }`}
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                <span className="hidden md:inline">{label}</span>
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          {user ? (
            <>
              <div className="hidden sm:flex items-center gap-2 text-sm text-slate-300 bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg max-w-[14rem]">
                <UserIcon className="w-4 h-4 text-amber-400 flex-shrink-0" />
                <span className="truncate">{user.name || user.email}</span>
              </div>
              <button
                onClick={logout}
                className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-rose-400 hover:border-rose-900/50 transition"
                title="Log out"
                aria-label="Log out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </>
          ) : (
            <>
              <Link
                to="/login"
                className="px-3 sm:px-4 py-2 text-sm font-medium text-slate-300 hover:text-white transition"
              >
                Log in
              </Link>
              <Link
                to="/register"
                className="px-3 sm:px-4 py-2 text-sm bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold rounded-lg shadow-md shadow-amber-500/10 transition whitespace-nowrap"
              >
                Sign up
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
