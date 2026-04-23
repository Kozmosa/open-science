import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from 'xterm';
import 'xterm/css/xterm.css';
import { useEffect, useRef, useState } from 'react';
import type { TerminalAttachmentMode, TerminalSessionStatus } from '../../types';
import { useT } from '../../i18n';
import { useTerminalFontSize } from '../../settings';

type SocketStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';

interface Props {
  sessionId: string | null;
  attachmentId: string | null;
  terminalWsUrl: string | null;
  status: TerminalSessionStatus;
  onDisconnected?: () => void;
  readonly?: boolean;
  mode?: TerminalAttachmentMode;
  placeholderText?: string;
}

interface SocketOutputMessage {
  type: 'output';
  data: string;
}

interface SocketStatusMessage {
  type: 'status';
  status: 'exited';
  return_code: number;
}

type SocketMessage = SocketOutputMessage | SocketStatusMessage;

function resolveWebSocketUrl(url: string): string {
  const resolved = new URL(url, window.location.origin);
  if (resolved.protocol === 'http:') {
    resolved.protocol = 'ws:';
  } else if (resolved.protocol === 'https:') {
    resolved.protocol = 'wss:';
  }
  return resolved.toString();
}

function isSocketMessage(value: unknown): value is SocketMessage {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const record = value as Record<string, unknown>;
  if (record.type === 'output') {
    return typeof record.data === 'string';
  }

  if (record.type === 'status') {
    return record.status === 'exited' && typeof record.return_code === 'number';
  }

  return false;
}

function TerminalSessionConsole({
  sessionId,
  attachmentId,
  terminalWsUrl,
  status,
  onDisconnected,
  readonly = false,
  mode = 'write',
  placeholderText,
}: Props) {
  const t = useT();
  const fontSize = useTerminalFontSize();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const onDisconnectedRef = useRef(onDisconnected);
  const translateRef = useRef(t);
  const disconnectNotifiedRef = useRef(false);
  const [socketStatus, setSocketStatus] = useState<SocketStatus>('idle');
  const isObserveOnly = readonly || mode === 'observe';
  const displaySocketStatus =
    status !== 'running' || terminalWsUrl === null
      ? 'idle'
      : socketStatus === 'idle'
        ? 'connecting'
        : socketStatus;
  const connectionLabel: Record<SocketStatus, string> = {
    idle: t('common.idle'),
    connecting: t('common.connecting'),
    connected: t('common.connected'),
    disconnected: t('common.disconnected'),
    error: t('common.error'),
  };

  useEffect(() => {
    onDisconnectedRef.current = onDisconnected;
  }, [onDisconnected]);

  useEffect(() => {
    translateRef.current = t;
  }, [t]);

  useEffect(() => {
    if (status !== 'running' || terminalWsUrl === null || containerRef.current === null) {
      disconnectNotifiedRef.current = false;
      return;
    }

    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: !isObserveOnly,
      fontFamily: 'var(--mono)',
      fontSize,
      scrollback: 2000,
      theme: {
        background: '#0b1020',
        foreground: '#e5eefc',
        cursor: '#c084fc',
        selectionBackground: '#334155',
      },
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(containerRef.current);
    terminal.focus();

    const socket = new WebSocket(resolveWebSocketUrl(terminalWsUrl));
    let disposed = false;

    const resizeDisposable = terminal.onResize(({ cols, rows }) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'resize', cols, rows }));
      }
    });

    const inputDisposable = isObserveOnly
      ? { dispose: () => {} }
      : terminal.onData((data) => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'input', data }));
          }
        });

    const fitTerminal = () => {
      try {
        fitAddon.fit();
      } catch {
        // ignore fit failures while the container is hidden or resizing
      }
    };

    const notifyDisconnected = () => {
      if (disconnectNotifiedRef.current) {
        return;
      }
      disconnectNotifiedRef.current = true;
      onDisconnectedRef.current?.();
    };

    const handleWindowResize = () => {
      fitTerminal();
    };

    socket.onopen = () => {
      if (disposed) {
        return;
      }
      setSocketStatus('connected');
      fitTerminal();
      socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }));
    };

    socket.onmessage = (event) => {
      if (disposed || typeof event.data !== 'string') {
        return;
      }

      try {
        const payload: unknown = JSON.parse(event.data) as unknown;
        if (!isSocketMessage(payload)) {
          terminal.write(event.data);
          return;
        }

        if (payload.type === 'output') {
          terminal.write(payload.data);
          return;
        }

        if (payload.type === 'status' && payload.status === 'exited') {
          terminal.writeln('');
          terminal.writeln(translateRef.current('components.terminalConsole.exited', { code: payload.return_code }));
          setSocketStatus('disconnected');
          notifyDisconnected();
        }
        return;
      } catch {
        terminal.write(event.data);
      }
    };

    socket.onerror = () => {
      if (!disposed) {
        setSocketStatus('error');
      }
    };

    socket.onclose = () => {
      if (!disposed) {
        setSocketStatus((current) => (current === 'connected' ? 'disconnected' : current));
        notifyDisconnected();
      }
    };

    window.addEventListener('resize', handleWindowResize);
    fitTerminal();

    return () => {
      disposed = true;
      window.removeEventListener('resize', handleWindowResize);
      resizeDisposable.dispose();
      inputDisposable.dispose();
      socket.close();
      terminal.dispose();
      disconnectNotifiedRef.current = false;
    };
  }, [fontSize, isObserveOnly, sessionId, status, terminalWsUrl]);

  if (status !== 'running' || terminalWsUrl === null) {
    return (
      <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 p-6 text-sm text-gray-500">
        {placeholderText ?? t('components.terminalConsole.startPrompt')}
      </div>
    );
  }

  return (
    <section className="space-y-3 rounded-xl border border-gray-200 bg-gray-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">
            {isObserveOnly
              ? t('components.terminalConsole.observeOnly')
              : t('components.terminalConsole.writeEnabled')}
          </h3>
          <p className="text-sm text-gray-600">
            {t('components.terminalConsole.websocketSession')}{' '}
            <code className="rounded bg-gray-100 px-1.5 py-0.5">{sessionId ?? 'n/a'}</code>
          </p>
          <p className="text-sm text-gray-600">
            {t('components.terminalConsole.attachment')} <code className="rounded bg-gray-100 px-1.5 py-0.5">{attachmentId ?? 'n/a'}</code>
          </p>
          <p
            className={[
              'text-xs font-medium uppercase tracking-[0.18em]',
              isObserveOnly ? 'text-amber-700' : 'text-emerald-700',
            ].join(' ')}
          >
            {isObserveOnly
              ? t('components.terminalConsole.observeOnly')
              : t('components.terminalConsole.writeEnabled')}
          </p>
        </div>
        <div className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700">
          {t('components.terminalConsole.connection')} {connectionLabel[displaySocketStatus]}
        </div>
      </div>

      <div
        ref={containerRef}
        className="min-h-[480px] overflow-hidden rounded-lg border border-gray-800 bg-[#0b1020]"
      />
    </section>
  );
}

export default TerminalSessionConsole;
