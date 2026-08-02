import React, { useState } from 'react';
import type { Artwork } from '../services/api';
import { Calendar, Palette, X, MessageSquare, ExternalLink, Check, Plus } from 'lucide-react';

interface ArtworkCardProps {
  artwork: Artwork;
  onSelect?: (artwork: Artwork) => void;
  /** Add/remove this artwork from a multi-artwork selection. */
  onToggleSelect?: (artwork: Artwork) => void;
  isSelected?: boolean;
}

export const ArtworkCard: React.FC<ArtworkCardProps> = ({
  artwork,
  onSelect,
  onToggleSelect,
  isSelected = false,
}) => {
  const [showModal, setShowModal] = useState(false);
  const [imgError, setImgError] = useState(false);

  const imageUrl = artwork.image_url.startsWith('/')
    ? `http://localhost:8000${artwork.image_url}`
    : artwork.image_url;

  const handleCardClick = () => setShowModal(true);

  return (
    <>
      {/* Card */}
      <div
        className={`group relative bg-slate-900 border rounded-2xl overflow-hidden cursor-pointer transition-all duration-300 hover:shadow-xl hover:shadow-amber-500/5 hover:-translate-y-1 ${
          isSelected
            ? 'border-amber-500 shadow-lg shadow-amber-500/20'
            : 'border-slate-800 hover:border-amber-500/40'
        }`}
        onClick={handleCardClick}
      >
        {/* Multi-select toggle — several references can be combined into one piece */}
        {onToggleSelect && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onToggleSelect(artwork);
            }}
            aria-label={isSelected ? `Remove ${artwork.title} from selection` : `Add ${artwork.title} to selection`}
            aria-pressed={isSelected}
            className={`absolute top-3 right-3 z-20 w-8 h-8 rounded-full flex items-center justify-center transition backdrop-blur-sm ${
              isSelected
                ? 'bg-amber-500 text-slate-950'
                : 'bg-slate-950/70 text-slate-300 opacity-0 group-hover:opacity-100 hover:bg-slate-800'
            }`}
          >
            {isSelected ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
          </button>
        )}

        {/* Image */}
        <div className="relative aspect-[4/3] overflow-hidden bg-slate-800">
          {!imgError ? (
            <img
              src={imageUrl}
              alt={artwork.title}
              className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
              onError={() => setImgError(true)}
            />
          ) : (
            <div
              className="w-full h-full flex items-center justify-center"
              style={{ backgroundColor: artwork.dominant_color ?? '#1e293b' }}
            >
              <Palette className="w-12 h-12 text-white/20" />
            </div>
          )}

          {/* Hover Overlay */}
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-slate-950/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-end p-4">
            <span className="text-xs text-amber-400 font-medium tracking-wide uppercase">
              View Details
            </span>
          </div>

          {/* Upload badge */}
          {artwork.is_custom_upload && (
            <div className="absolute top-3 left-3 px-2 py-1 rounded-full bg-purple-500/80 backdrop-blur-sm text-xs font-medium text-white">
              My Upload
            </div>
          )}
        </div>

        {/* Info */}
        <div className="p-4">
          <h3 className="font-semibold text-slate-100 truncate text-sm leading-tight">
            {artwork.title}
          </h3>
          <p className="text-slate-400 text-xs mt-1 truncate">{artwork.artist}</p>
          <div className="flex items-center gap-3 mt-2">
            {artwork.year && (
              <span className="flex items-center gap-1 text-xs text-slate-500">
                <Calendar className="w-3 h-3" />
                {artwork.year}
              </span>
            )}
            {artwork.movement_style && (
              <span className="text-xs text-amber-500/70 truncate">{artwork.movement_style}</span>
            )}
          </div>
        </div>

        {/* Color accent bar */}
        {artwork.dominant_color && (
          <div
            className="h-0.5 w-0 group-hover:w-full transition-all duration-500"
            style={{ backgroundColor: artwork.dominant_color }}
          />
        )}
      </div>

      {/* Detail Modal */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm"
          onClick={() => setShowModal(false)}
        >
          <div
            className="relative max-w-2xl w-full bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close button */}
            <button
              onClick={() => setShowModal(false)}
              className="absolute top-4 right-4 z-10 p-2 rounded-full bg-slate-800/80 backdrop-blur-sm text-slate-400 hover:text-white transition"
            >
              <X className="w-4 h-4" />
            </button>

            {/* Image */}
            <div className="relative h-72 sm:h-96 bg-slate-800">
              {!imgError ? (
                <img
                  src={imageUrl}
                  alt={artwork.title}
                  className="w-full h-full object-contain"
                />
              ) : (
                <div
                  className="w-full h-full flex items-center justify-center"
                  style={{ backgroundColor: artwork.dominant_color ?? '#1e293b' }}
                >
                  <Palette className="w-16 h-16 text-white/20" />
                </div>
              )}
            </div>

            {/* Info Panel */}
            <div className="p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-xl font-bold text-slate-100">{artwork.title}</h2>
                  <p className="text-slate-400 mt-1">{artwork.artist}{artwork.year ? ` · ${artwork.year}` : ''}</p>
                </div>
                {artwork.movement_style && (
                  <span className="flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    {artwork.movement_style}
                  </span>
                )}
              </div>

              {artwork.medium && (
                <p className="mt-2 text-sm text-slate-500 italic">{artwork.medium}</p>
              )}

              {artwork.description && (
                <p className="mt-4 text-sm text-slate-300 leading-relaxed line-clamp-4">
                  {artwork.description}
                </p>
              )}

              {artwork.source_attribution && (
                <p className="mt-3 text-xs text-slate-600 flex items-center gap-1">
                  <ExternalLink className="w-3 h-3" />
                  {artwork.source_attribution}
                </p>
              )}

              {/* CTA */}
              <button
                onClick={() => {
                  if (onSelect) onSelect(artwork);
                  setShowModal(false);
                }}
                className="mt-6 w-full py-3 px-4 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2 transition"
              >
                <MessageSquare className="w-5 h-5" />
                Start a Conversation About This Artwork
              </button>

              {onToggleSelect && (
                <button
                  onClick={() => {
                    onToggleSelect(artwork);
                    setShowModal(false);
                  }}
                  className={`mt-3 w-full py-2.5 px-4 rounded-xl border font-medium text-sm flex items-center justify-center gap-2 transition ${
                    isSelected
                      ? 'border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20'
                      : 'border-slate-700 bg-slate-800/60 text-slate-300 hover:text-slate-100 hover:border-slate-600'
                  }`}
                >
                  {isSelected ? <Check className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
                  {isSelected ? 'Remove from selection' : 'Add to a multi-artwork blend'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
};
