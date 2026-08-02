import React, { useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Upload, X, CheckCircle2, AlertCircle, ImagePlus, Loader2, ArrowLeft, MessageSquare } from 'lucide-react';
import { artworksApi, sessionsApi } from '../services/api';
import type { Artwork } from '../services/api';
import { useAuth } from '../context/AuthContext';

interface FilePreview {
  file: File;
  previewUrl: string;
  status: 'pending' | 'uploading' | 'success' | 'error';
  error?: string;
  result?: Artwork;
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const MAX_SIZE_MB = 10;

function validateFile(file: File): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return `Unsupported type. Only JPEG, PNG, and WebP are accepted.`;
  }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    return `File too large (${(file.size / (1024 * 1024)).toFixed(1)} MB). Max is 10 MB.`;
  }
  return null;
}

export const UploadPage: React.FC = () => {
  const [previews, setPreviews] = useState<FilePreview[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isStartingConversation, setIsStartingConversation] = useState(false);
  const [startError, setStartError] = useState('');
  const [uploadedArtworks, setUploadedArtworks] = useState<Artwork[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { user } = useAuth();
  const navigate = useNavigate();

  const addFiles = (files: File[]) => {
    const newPreviews: FilePreview[] = files.map((file) => {
      const validationError = validateFile(file);
      return {
        file,
        previewUrl: validationError ? '' : URL.createObjectURL(file),
        status: validationError ? 'error' : 'pending',
        error: validationError ?? undefined,
      };
    });
    setPreviews((prev) => [...prev, ...newPreviews]);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    addFiles(files);
  }, []);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    addFiles(files);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removePreview = (index: number) => {
    setPreviews((prev) => {
      const updated = [...prev];
      if (updated[index].previewUrl) URL.revokeObjectURL(updated[index].previewUrl);
      updated.splice(index, 1);
      return updated;
    });
  };

  const handleUpload = async () => {
    const validFiles = previews
      .filter((p) => p.status === 'pending')
      .map((p) => p.file);

    if (validFiles.length === 0) return;

    if (!user) {
      navigate('/login');
      return;
    }

    setIsUploading(true);
    // Mark all pending as uploading
    setPreviews((prev) =>
      prev.map((p) => (p.status === 'pending' ? { ...p, status: 'uploading' } : p))
    );

    try {
      const res = await artworksApi.upload(validFiles);
      const uploaded = res.data;
      setUploadedArtworks((prev) => [...prev, ...uploaded]);

      // Match results back to previews by order
      setPreviews((prev) => {
        let uploadIdx = 0;
        return prev.map((p) => {
          if (p.status === 'uploading' && uploadIdx < uploaded.length) {
            const result = uploaded[uploadIdx++];
            return { ...p, status: 'success', result };
          }
          return p;
        });
      });
    } catch (err: any) {
      const detail = err.response?.data?.detail || 'Upload failed. Please try again.';
      setPreviews((prev) =>
        prev.map((p) =>
          p.status === 'uploading' ? { ...p, status: 'error', error: detail } : p
        )
      );
    } finally {
      setIsUploading(false);
    }
  };

  const pendingCount = previews.filter((p) => p.status === 'pending').length;
  const successCount = previews.filter((p) => p.status === 'success').length;

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10">
      {/* Back navigation */}
      <button
        onClick={() => navigate('/library')}
        className="flex items-center gap-2 text-slate-400 hover:text-slate-100 transition text-sm mb-6"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Library
      </button>

      <h1 className="text-3xl font-extrabold text-slate-100 tracking-tight mb-2">
        Upload Your Reference
      </h1>
      <p className="text-slate-400 text-sm mb-8">
        Upload your own artwork or photo to use as inspiration. Accepts JPEG, PNG, or WebP — up to 10 MB each.
      </p>

      {/* Drop Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`
          relative border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all
          ${isDragging
            ? 'border-amber-500 bg-amber-500/5 scale-[1.01]'
            : 'border-slate-700 hover:border-amber-500/50 hover:bg-slate-900/50'
          }
        `}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/jpeg,image/png,image/webp"
          onChange={handleFileInput}
          className="hidden"
        />
        <div className="flex flex-col items-center gap-3 pointer-events-none">
          <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition ${isDragging ? 'bg-amber-500/20' : 'bg-slate-800'}`}>
            <ImagePlus className={`w-8 h-8 transition ${isDragging ? 'text-amber-400' : 'text-slate-500'}`} />
          </div>
          <div>
            <p className="text-slate-200 font-medium">
              {isDragging ? 'Drop your images here' : 'Drag & drop images here'}
            </p>
            <p className="text-slate-500 text-sm mt-1">or click to browse files</p>
          </div>
          <p className="text-xs text-slate-600">JPEG, PNG, WebP · Up to 10 MB per file · Multiple files supported</p>
        </div>
      </div>

      {/* Previews */}
      {previews.length > 0 && (
        <div className="mt-8 space-y-3">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide">
            {previews.length} file{previews.length !== 1 ? 's' : ''} selected
          </h2>
          <div className="grid grid-cols-1 gap-3">
            {previews.map((preview, index) => (
              <div
                key={index}
                className={`flex items-center gap-4 p-4 rounded-xl border transition ${
                  preview.status === 'success'
                    ? 'border-emerald-500/30 bg-emerald-500/5'
                    : preview.status === 'error'
                    ? 'border-rose-500/30 bg-rose-500/5'
                    : 'border-slate-800 bg-slate-900'
                }`}
              >
                {/* Thumbnail */}
                <div className="w-16 h-16 flex-shrink-0 rounded-lg overflow-hidden bg-slate-800">
                  {preview.previewUrl ? (
                    <img src={preview.previewUrl} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <AlertCircle className="w-6 h-6 text-rose-400" />
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-slate-200 truncate">{preview.file.name}</p>
                  <p className="text-xs text-slate-500">{(preview.file.size / (1024 * 1024)).toFixed(2)} MB</p>
                  {preview.error && (
                    <p className="text-xs text-rose-400 mt-1">{preview.error}</p>
                  )}
                  {preview.status === 'success' && (
                    <p className="text-xs text-emerald-400 mt-1">Uploaded successfully</p>
                  )}
                </div>

                {/* Status icon */}
                <div className="flex-shrink-0">
                  {preview.status === 'uploading' && (
                    <Loader2 className="w-5 h-5 text-amber-400 animate-spin" />
                  )}
                  {preview.status === 'success' && (
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  )}
                  {preview.status === 'error' && (
                    <AlertCircle className="w-5 h-5 text-rose-400" />
                  )}
                  {preview.status === 'pending' && (
                    <button
                      onClick={(e) => { e.stopPropagation(); removePreview(index); }}
                      className="p-1 rounded-lg hover:bg-slate-700 text-slate-500 hover:text-slate-200 transition"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Upload Button */}
          {pendingCount > 0 && (
            <button
              onClick={handleUpload}
              disabled={isUploading}
              className="mt-4 w-full py-3 px-4 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 hover:from-amber-400 hover:to-rose-400 text-slate-950 font-semibold shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2 transition disabled:opacity-50"
            >
              {isUploading ? (
                <><Loader2 className="w-5 h-5 animate-spin" /> Uploading…</>
              ) : (
                <><Upload className="w-5 h-5" /> Upload {pendingCount} file{pendingCount !== 1 ? 's' : ''}</>
              )}
            </button>
          )}
        </div>
      )}

      {/* Post-upload CTAs */}
      {successCount > 0 && uploadedArtworks.length > 0 && (
        <div className="mt-8 p-6 rounded-2xl bg-emerald-500/5 border border-emerald-500/20 text-center space-y-4">
          <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto" />
          <p className="text-emerald-300 font-semibold">
            {successCount} artwork{successCount !== 1 ? 's' : ''} uploaded successfully!
          </p>
          <p className="text-sm text-slate-400">
            Muse is looking at {successCount !== 1 ? 'these images' : 'this image'} now, so it can ask
            about what's actually in {successCount !== 1 ? 'them' : 'it'}.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            {/* All uploads from this batch go into one session — the client
                asked for multiple references to be combinable. */}
            <button
              onClick={async () => {
                if (uploadedArtworks.length === 0) return;
                setIsStartingConversation(true);
                setStartError('');
                try {
                  const res = await sessionsApi.create(uploadedArtworks.map((a) => a.id));
                  navigate(`/session/${res.data.id}`);
                } catch {
                  setStartError('Failed to start a conversation. Please try again.');
                } finally {
                  setIsStartingConversation(false);
                }
              }}
              disabled={isStartingConversation}
              className="flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-rose-500 text-slate-950 font-semibold transition disabled:opacity-50"
            >
              {isStartingConversation ? <Loader2 className="w-4 h-4 animate-spin" /> : <MessageSquare className="w-4 h-4" />}
              {uploadedArtworks.length > 1
                ? `Start a conversation with all ${uploadedArtworks.length}`
                : 'Start a Conversation'}
            </button>
            <button
              onClick={() => navigate('/library')}
              className="flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-slate-800 border border-slate-700 text-slate-200 hover:text-white transition"
            >
              View in Library
            </button>
          </div>
          {startError && (
            <p className="text-sm text-rose-400">{startError}</p>
          )}
        </div>
      )}
    </div>
  );
};
