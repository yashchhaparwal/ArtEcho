import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Sparkles, Trash2, Loader2, ImageOff, ArrowRight,
  Palette, AlertCircle, Calendar, ExternalLink
} from 'lucide-react';
import { galleryApi, sessionsApi } from '../services/api';
import type { GalleryItem } from '../services/api';

import { resolveAssetUrl } from '../config';

function resolveImageUrl(url?: string): string {
  return resolveAssetUrl(url);
}

export const GalleryPage: React.FC = () => {
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteModalItem, setDeleteModalItem] = useState<GalleryItem | null>(null);

  const navigate = useNavigate();

  const fetchGallery = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await galleryApi.getSaved();
      setItems(res.data.items);
    } catch {
      setError('Failed to load gallery. Make sure you are logged in.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGallery();
  }, [fetchGallery]);

  const handleDeleteConfirm = async () => {
    if (!deleteModalItem) return;
    const sid = deleteModalItem.session_id;
    setDeletingId(sid);
    try {
      await sessionsApi.deleteSession(sid);
      setItems((prev) => prev.filter((i) => i.session_id !== sid));
      setDeleteModalItem(null);
    } catch {
      setError('Failed to delete session. Please try again.');
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[70vh] text-slate-500">
        <Loader2 className="w-8 h-8 animate-spin mr-3 text-amber-400" />
        Loading your gallery…
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-100 tracking-tight">
            My Art Gallery
          </h1>
          <p className="text-slate-400 mt-1 text-sm">
            {items.length} saved artwork synthesis{items.length !== 1 ? 'es' : ''}
          </p>
        </div>
        <Link
          to="/library"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold shadow-lg shadow-amber-500/20 transition text-sm"
        >
          <Sparkles className="w-4 h-4" />
          Create New Artwork
        </Link>
      </div>

      {/* Error alert */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-between text-rose-300 text-sm">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-400" />
            <span>{error}</span>
          </div>
          <button onClick={fetchGallery} className="text-amber-400 hover:underline text-xs">
            Retry
          </button>
        </div>
      )}

      {/* Empty State */}
      {items.length === 0 && !error && (
        <div className="flex flex-col items-center justify-center py-20 bg-slate-900/50 border border-slate-800 rounded-3xl p-8 text-center max-w-lg mx-auto">
          <div className="w-16 h-16 rounded-2xl bg-amber-500/10 flex items-center justify-center mb-4 border border-amber-500/20">
            <Palette className="w-8 h-8 text-amber-400" />
          </div>
          <h3 className="text-xl font-bold text-slate-200 mb-2">Your Gallery is Empty</h3>
          <p className="text-slate-400 text-sm mb-6 leading-relaxed">
            You haven't saved any generated artwork yet. Browse the public-domain library, have a guided conversation with Muse, and co-create your first piece!
          </p>
          <Link
            to="/library"
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 text-slate-950 font-semibold text-sm shadow-lg shadow-amber-500/20 transition"
          >
            Explore Artwork Library
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      )}

      {/* Gallery Grid */}
      {items.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {items.map((item) => {
            const refArt = item.reference_artwork;
            const genArt = item.latest_generated_artwork;
            const refImg = resolveImageUrl(refArt?.image_url);
            const genImg = resolveImageUrl(genArt?.image_url);

            return (
              <div
                key={item.session_id}
                className="group relative bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-lg transition-all duration-300 hover:border-amber-500/40 hover:-translate-y-1"
              >
                {/* Side-by-side thumbnails */}
                <div
                  className="grid grid-cols-2 aspect-[16/9] overflow-hidden bg-slate-950 cursor-pointer relative"
                  onClick={() => navigate(`/session/${item.session_id}/result`)}
                >
                  {/* Left: Reference */}
                  <div className="relative border-r border-slate-800 overflow-hidden bg-slate-900">
                    {refImg ? (
                      <img src={refImg} alt={refArt?.title || 'Reference'} className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <ImageOff className="w-6 h-6 text-slate-700" />
                      </div>
                    )}
                    <span className="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-slate-950/80 backdrop-blur-sm text-[10px] font-medium text-slate-300">
                      Original
                    </span>
                  </div>

                  {/* Right: Generated */}
                  <div className="relative overflow-hidden bg-slate-900">
                    {genImg ? (
                      <img src={genImg} alt="Generated" className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Palette className="w-6 h-6 text-amber-500/40 animate-pulse" />
                      </div>
                    )}
                    <span className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-amber-500/80 backdrop-blur-sm text-[10px] font-semibold text-slate-950">
                      Generated
                    </span>
                  </div>

                  {/* Hover Overlay */}
                  <div className="absolute inset-0 bg-slate-950/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                    <span className="px-4 py-2 rounded-xl bg-amber-500 text-slate-950 font-semibold text-xs flex items-center gap-1.5 shadow-lg">
                      View Critique & Result
                      <ExternalLink className="w-3.5 h-3.5" />
                    </span>
                  </div>
                </div>

                {/* Card Content */}
                <div className="p-5 flex items-start justify-between gap-3">
                  <div
                    className="min-w-0 cursor-pointer"
                    onClick={() => navigate(`/session/${item.session_id}/result`)}
                  >
                    <h3 className="font-semibold text-slate-100 text-sm truncate leading-snug">
                      {item.title}
                    </h3>
                    <p className="text-xs text-slate-400 mt-1 truncate">
                      {refArt ? `${refArt.title} (${refArt.artist})` : 'Custom Reference'}
                    </p>
                    <div className="flex items-center gap-2 mt-2 text-xs text-slate-500">
                      <Calendar className="w-3 h-3" />
                      <span>
                        Saved {new Date(item.saved_at || item.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteModalItem(item);
                    }}
                    className="p-2 rounded-xl bg-slate-800/80 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 transition flex-shrink-0"
                    title="Delete saved item"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteModalItem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm"
          onClick={() => setDeleteModalItem(null)}
        >
          <div
            className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-slate-100 text-base">Delete from Gallery?</h3>
                <p className="text-xs text-slate-400">This action cannot be undone.</p>
              </div>
            </div>

            <p className="text-sm text-slate-300 leading-relaxed">
              Are you sure you want to delete <span className="font-semibold text-slate-100">"{deleteModalItem.title}"</span>? This will permanently delete the conversation history, generated artwork, critique, and saved image files from disk.
            </p>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setDeleteModalItem(null)}
                className="px-4 py-2.5 rounded-xl bg-slate-800 text-slate-300 hover:text-white transition text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteConfirm}
                disabled={deletingId === deleteModalItem.session_id}
                className="px-5 py-2.5 rounded-xl bg-rose-500 hover:bg-rose-400 text-white font-semibold text-sm shadow-lg shadow-rose-500/20 transition flex items-center gap-2"
              >
                {deletingId === deleteModalItem.session_id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
                Delete Permanently
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
