import React from 'react';
import { AlertCircle } from 'lucide-react';

interface State {
  hasError: boolean;
  error?: Error | null;
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: any) {
    // eslint-disable-next-line no-console
    console.error('Unhandled error caught by ErrorBoundary:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-100">
          <div className="max-w-xl mx-auto p-8 bg-slate-900/90 border border-slate-800 rounded-2xl text-center">
            <div className="flex items-center justify-center mb-4">
              <AlertCircle className="w-8 h-8 text-rose-400 mr-2" />
              <h2 className="text-lg font-bold">Something went wrong</h2>
            </div>
            <p className="text-sm text-slate-400 mb-4">An unexpected error occurred. Check the console for details.</p>
            <pre className="text-xs text-slate-300 bg-slate-800 p-3 rounded overflow-auto">{this.state.error?.message}</pre>
          </div>
        </div>
      );
    }

    return this.props.children as React.ReactElement;
  }
}

export default ErrorBoundary;
