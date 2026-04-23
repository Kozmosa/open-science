import { Component, type ErrorInfo, type ReactNode, type ContextType } from 'react';
import { I18nContext } from '../../i18n';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  static contextType = I18nContext;
  declare context: ContextType<typeof I18nContext>;

  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      const t = this.context.t;
      return (
        this.props.fallback || (
          <div className="rounded-lg bg-[#272729] p-5 text-white">
            <h2
              className="text-lg font-semibold leading-tight tracking-[0.231px]"
              style={{ fontFamily: 'var(--font-display)' }}
            >
              {t('components.errorBoundary.title')}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-white/70 tracking-[-0.224px]">
              {this.state.error?.message}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-4 rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)]"
            >
              {t('components.errorBoundary.retry')}
            </button>
          </div>
        )
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
