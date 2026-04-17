/**
 * ErrorBoundary — Global React Error Boundary with friendly user-facing degradation notice.
 * BUG-007: Catches unexpected JS crashes and shows a recovery UI instead of blank screen.
 */
import { Component, ReactNode } from 'react';
import { AlertTriangle, RefreshCcw, ChevronDown, ChevronUp } from 'lucide-react';

interface Props {
  children: ReactNode;
  tabName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  showDetails: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, showDetails: false };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[CryptoStream ErrorBoundary]', error, info);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, showDetails: false });
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const { tabName = 'Module' } = this.props;
    const errorMsg = this.state.error?.message || 'Unknown error';
    const isNetworkError = errorMsg.toLowerCase().includes('fetch') || errorMsg.toLowerCase().includes('network');

    return (
      <div className="flex-1 flex items-center justify-center p-10 min-h-[400px]">
        <div className="w-full max-w-lg bg-slate-900/60 backdrop-blur-2xl border border-rose-500/20 rounded-[2rem] p-10 space-y-6 shadow-2xl shadow-rose-900/20">
          {/* Icon */}
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-rose-600/10 rounded-2xl flex items-center justify-center border border-rose-500/20 shrink-0">
              <AlertTriangle className="w-7 h-7 text-rose-400" />
            </div>
            <div>
              <h2 className="text-lg font-black text-white uppercase tracking-tight">
                {tabName} Unavailable
              </h2>
              <p className="text-[11px] font-bold text-rose-400 uppercase tracking-widest mt-1">
                {isNetworkError ? 'Connection Error' : 'Render Error'}
              </p>
            </div>
          </div>

          {/* Message */}
          <div className="space-y-2">
            <p className="text-sm text-slate-400 leading-relaxed">
              {isNetworkError
                ? 'ระบบไม่สามารถดึงข้อมูลได้ในขณะนี้ กรุณาตรวจสอบว่า Backend และ Docker ทำงานอยู่ หรือลองใหม่อีกครั้ง'
                : 'เกิดข้อผิดพลาดขณะแสดงผลส่วนนี้ ข้อมูลยังคงอยู่ครบถ้วน คุณสามารถลอง Reset ได้เลย'}
            </p>

            {/* Collapsible technical details */}
            <button
              onClick={() => this.setState(s => ({ showDetails: !s.showDetails }))}
              className="flex items-center gap-1.5 text-xs font-bold text-slate-600 hover:text-slate-400 uppercase tracking-widest transition-colors mt-2"
            >
              {this.state.showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              Technical Details
            </button>

            {this.state.showDetails && (
              <div className="mt-2 p-4 bg-slate-950/60 rounded-xl border border-white/5 overflow-auto max-h-32">
                <code className="text-xs text-rose-300 font-mono break-words whitespace-pre-wrap">
                  {this.state.error?.stack || errorMsg}
                </code>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={this.handleReset}
              className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-2xl text-xs font-black uppercase tracking-widest transition-all shadow-lg shadow-blue-600/20 active:scale-95"
            >
              <RefreshCcw className="w-4 h-4" />
              Reset Module
            </button>
            <button
              onClick={() => window.location.reload()}
              className="flex items-center gap-2 px-6 py-3 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-2xl text-xs font-black uppercase tracking-widest transition-all active:scale-95"
            >
              Full Reload
            </button>
          </div>
        </div>
      </div>
    );
  }
}
