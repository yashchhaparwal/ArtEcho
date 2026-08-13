import React from 'react';
import { Outlet } from 'react-router-dom';
import { Navbar } from './Navbar';

export const Layout: React.FC = () => {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-amber-500 selection:text-slate-950">
      {/* Dynamic Background Glow Effects */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-40 -left-40 w-96 h-96 bg-purple-900/30 rounded-full blur-3xl" />
        <div className="absolute top-1/3 -right-40 w-96 h-96 bg-amber-900/20 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 left-1/3 w-96 h-96 bg-indigo-900/30 rounded-full blur-3xl" />
      </div>

      <Navbar />

      <main className="relative z-10 flex-1">
        <Outlet />
      </main>

      {/* No top margin: the chat page sizes itself to the viewport, and any
          extra height here pushes the document into a window-level scroll that
          drags its header out of view. */}
      <footer className="relative z-10 border-t border-slate-800/80 bg-slate-950/60 py-6">
        <div className="max-w-7xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-2 text-sm text-slate-500">
          <p>Muse — guided art conversation &amp; AI artwork synthesis</p>
          <p className="text-xs text-slate-600">
            Public-domain library · runs entirely on free, local models
          </p>
        </div>
      </footer>
    </div>
  );
};
