import { Component, type ErrorInfo, type ReactNode, type ContextType } from 'react';
import { Alert, Button } from '../ui';
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
          <Alert variant="error">
            <div className="space-y-2">
              <h2
                className="text-lg font-semibold leading-tight tracking-[0.231px]"
                style={{ fontFamily: 'var(--font-display)' }}
              >
                {t('components.errorBoundary.title')}
              </h2>
              <p className="text-sm leading-relaxed text-white/70 tracking-[-0.224px]">
                {this.state.error?.message}
              </p>
              <Button
                variant="primary"
                onClick={() => this.setState({ hasError: false, error: null })}
              >
                {t('components.errorBoundary.retry')}
              </Button>
            </div>
          </Alert>
        )
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
