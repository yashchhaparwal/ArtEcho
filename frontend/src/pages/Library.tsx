import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { Search, SlidersHorizontal, Loader2, ImageOff, Upload, X, Sparkles } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { artworksApi, sessionsApi } from '../services/api';
import type { Artwork } from '../services/api';
import { ArtworkCard } from '../components/ArtworkCard';
import { useAuth } from '../context/AuthContext';
import { resolveAssetUrl } from '../config';

const PAGE_SIZE = 24;

// The client asked for multiple references to be combinable. Past a handful the
// blend stops reading as any of them, so the tray caps the selection.
const MAX_SELECTION = 4;

export const Library: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [artworks, setArtworks] = useState<Artwork[]>([]);
  const [movements, setMovements] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectError, setSelectError] = useState('');
  const [starting, setStarting] = useState(false);

  const [selected, setSelected] = useState<Artwork[]>([]);

  const [search, setSearch] = useState('');
  const [artistFilter, setArtistFilter] = useState('');
  const [movementFilter, setMovementFilter] = useState('');
  const [includeUploads, setIncludeUploads] = useState(true);

  const fetchArtworks = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await artworksApi.list({
        search: search || undefined,
        artist: artistFilter || undefined,
        movement: movementFilter || undefined,
        include_uploads: includeUploads,
        page,
        page_size: PAGE_SIZE,
      });
      setArtworks(res.data.artworks);
      setTotal(res.data.total);
    } catch (err) {
      console.error('Failed to load artworks', err);
      setError('Failed to load the artwork library. Make sure the backend is running.');
    } finally {
      setLoading(false);
    }
  }, [search, artistFilter, movementFilter, includeUploads, page]);

  useEffect(() => {
    const timer = setTimeout(() => fetchArtworks(), 300);
    return () => clearTimeout(timer);
  }, [fetchArtworks]);

  // Movement options come from the library itself rather than a hard-coded list,
  // so adding artworks to the seed never leaves the filter out of date.
  useEffect(() => {
    artworksApi
      .list({ page: 1, page_size: 100, include_uploads: false })
      .then((res) => {
        const found = res.data.artworks
          .map((a) => a.movement_style)
          .filter((m): m is string => Boolean(m));
        setMovements([...new Set(found)].sort());
      })
      .catch(() => setMovements([]));
  }, []);

  // Filter changes should return to the first page, otherwise a narrow result
  // set renders empty while sitting on page 3.
  useEffect(() => {
    setPage(1);
  }, [search, artistFilter, movementFilter, includeUploads]);

  const startSession = async (artworkIds: string[]) => {
    setSelectError('');
    if (!user) {
      navigate('/login', { state: { from: '/library' } });
      return;
    }
    setStarting(true);
    try {
      const res = await sessionsApi.create(artworkIds);
      navigate(`/session/${res.data.id}`);
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 401) {
        navigate('/login', { state: { from: '/library' } });
        return;
      }
      setSelectError('Failed to start a conversation. Please try again.');
    } finally {
      setStarting(false);
    }
  };

  const handleSelect = (artwork: Artwork) => startSession([artwork.id]);

  const toggleSelect = (artwork: Artwork) => {
    setSelectError('');
    setSelected((prev) => {
      const exists = prev.some((a) => a.id === artwork.id);
      if (exists) return prev.filter((a) => a.id !== artwork.id);
      if (prev.length >= MAX_SELECTION) {
        setSelectError(`You can blend up to ${MAX_SELECTION} artworks at a time.`);
        return prev;
      }
      return [...prev, artwork];
    });
  };

  const clearFilters = () => {
    setSearch('');
    setArtistFilter('');
    setMovementFilter('');
    setIncludeUploads(true);
  };

  const hasFilters = search || artistFilter || movementFilter || !includeUploads;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 py-10">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-100 tracking-tight">
            Artwork Library
          </h1>
          <p className="text-slate-400 mt-1 text-sm">
            {loading ? 'Loading…' : `${total} public-domain masterpiece${total !== 1 ? 's' : ''}`}
          </p>
          <p className="text-slate-500 mt-1 text-xs">
            Click a work to open it, or use <span className="text-amber-400">+</span> to combine
            several into one blended piece.
          </p>
        </div>
        <Link
          to="/upload"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold shadow-lg shadow-amber-500/20 transition text-sm"
        >
          <Upload className="w-4 h-4" />
          Upload Your Own
        </Link>
      </div>

      {/* Search + Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-8">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search artworks, artists, descriptions…"
            className="w-full pl-10 pr-4 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500/60 transition text-sm"
          />
        </div>

        {/* Artist filter */}
        <input
          type="text"
          value={artistFilter}
          onChange={(e) => setArtistFilter(e.target.value)}
          placeholder="Filter by artist…"
          className="px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-amber-500/60 transition text-sm w-full sm:w-48"
        />

        {/* Movement dropdown */}
        <div className="relative">
          <SlidersHorizontal className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
          <select
            value={movementFilter}
            onChange={(e) => setMovementFilter(e.target.value)}
            className="pl-9 pr-8 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-100 focus:outline-none focus:border-amber-500/60 transition text-sm appearance-none cursor-pointer w-full sm:w-56"
          >
            <option value="">All Movements</option>
            {movements.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>

        {hasFilters && (
          <button
            onClick={clearFilters}
            className="px-4 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 hover:text-slate-100 transition text-sm whitespace-nowrap"
          >
            Clear
          </button>
        )}
      </div>

      {/* Include uploads toggle */}
      <div className="flex items-center gap-2 mb-6">
        <button
          onClick={() => setIncludeUploads(!includeUploads)}
          className={`relative w-10 h-5 rounded-full transition-colors ${includeUploads ? 'bg-amber-500' : 'bg-slate-700'}`}
        >
          <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${includeUploads ? 'left-[22px]' : 'left-0.5'}`} />
        </button>
        <span className="text-sm text-slate-400">Show my uploaded artworks</span>
      </div>

      {/* State: Error */}
      {error && (
        <div className="p-5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {error}
        </div>
      )}

      {/* Action error — shown above the grid without hiding it */}
      {selectError && (
        <div className="mb-5 p-5 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm">
          {selectError}
        </div>
      )}

      {/* State: Loading */}
      {loading && (
        <div className="flex items-center justify-center py-24 text-slate-500">
          <Loader2 className="w-8 h-8 animate-spin mr-3" />
          Loading artworks…
        </div>
      )}

      {/* State: Empty */}
      {!loading && !error && artworks.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
          <ImageOff className="w-12 h-12 text-slate-700" />
          <p className="text-base font-medium text-slate-400">No artworks found</p>
          <p className="text-sm">Try adjusting your search or filters</p>
          {hasFilters && (
            <button onClick={clearFilters} className="text-amber-400 hover:underline text-sm">
              Clear all filters
            </button>
          )}
        </div>
      )}

      {/* Grid */}
      {!loading && !error && artworks.length > 0 && (
        <div
          className={`grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5 ${
            selected.length > 0 ? 'pb-32' : ''
          }`}
        >
          {artworks.map((artwork) => (
            <ArtworkCard
              key={artwork.id}
              artwork={artwork}
              onSelect={handleSelect}
              onToggleSelect={toggleSelect}
              isSelected={selected.some((a) => a.id === artwork.id)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && !error && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-10">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-slate-100 hover:border-slate-700 transition text-sm disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-sm text-slate-500">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 hover:text-slate-100 hover:border-slate-700 transition text-sm disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}

      {/* Multi-artwork selection tray */}
      {selected.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-slate-800 bg-slate-950/95 backdrop-blur-md">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="flex items-center gap-2 flex-1 min-w-0 overflow-x-auto">
              {selected.map((artwork) => (
                <div
                  key={artwork.id}
                  className="relative flex-shrink-0 w-14 h-14 rounded-lg overflow-hidden border border-slate-700 group"
                  title={`${artwork.title} — ${artwork.artist}`}
                >
                  <img
                    src={resolveAssetUrl(artwork.image_url)}
                    alt={artwork.title}
                    className="w-full h-full object-cover"
                  />
                  <button
                    onClick={() => toggleSelect(artwork)}
                    aria-label={`Remove ${artwork.title}`}
                    className="absolute inset-0 bg-slate-950/70 opacity-0 group-hover:opacity-100 flex items-center justify-center transition"
                  >
                    <X className="w-4 h-4 text-rose-300" />
                  </button>
                </div>
              ))}
              <p className="text-sm text-slate-400 ml-2 whitespace-nowrap">
                {selected.length} artwork{selected.length !== 1 ? 's' : ''} selected
              </p>
            </div>

            <div className="flex items-center gap-3 flex-shrink-0">
              <button
                onClick={() => setSelected([])}
                className="px-4 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-400 hover:text-slate-100 transition text-sm"
              >
                Clear
              </button>
              <button
                onClick={() => startSession(selected.map((a) => a.id))}
                disabled={starting}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold shadow-lg shadow-amber-500/20 transition text-sm disabled:opacity-60"
              >
                {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                {selected.length === 1
                  ? 'Start a conversation'
                  : `Blend ${selected.length} artworks`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
