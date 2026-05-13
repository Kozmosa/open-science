import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { TerminalAttachmentMode, TerminalSessionStatus } from '../../types';
import { useT } from '../../i18n';
import { useTerminalFontSize } from '../../settings';
import { useTerminalFitScheduling } from './useTerminalFitScheduling';

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
  const socketRef = useRef<WebSocket | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const onDisconnectedRef = useRef(onDisconnected);
  const translateRef = useRef(t);
  const disconnectNotifiedRef = useRef(false);
  const [socketStatus, setSocketStatus] = useState<SocketStatus>('idle');
  const isObserveOnly = readonly || mode === 'observe';
  const isActive = status === 'running' && terminalWsUrl !== null;
  const displaySocketStatus = !isActive ? 'idle' : socketStatus === 'idle' ? 'connecting' : socketStatus;
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

  const sendJsonMessage = useCallback(
    (payload: { type: 'resize'; cols: number; rows: number } | { type: 'input'; data: string }) => {
      const socket = socketRef.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
      }

      if (payload.type === 'input' && isObserveOnly) {
        return;
      }

      socket.send(JSON.stringify(payload));
    },
    [isObserveOnly]
  );

  const { scheduleFitAndSendResize, sendResizeAfterFit } = useTerminalFitScheduling({
    active: isActive,
    containerRef,
    fitAddonRef,
    terminalRef,
  });

  const notifyDisconnected = useCallback(() => {
    if (disconnectNotifiedRef.current) {
      return;
    }
    disconnectNotifiedRef.current = true;
    onDisconnectedRef.current?.();
  }, []);

  useEffect(() => {
    if (!isActive || containerRef.current === null) {
      disconnectNotifiedRef.current = false;
      socketRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
      return undefined;
    }

    const terminal = new Terminal({
      convertEol: true,
      cursorBlink: !isObserveOnly,
      fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
      fontSize,
      scrollback: 2000,
      theme: {
        background: '#0b1020',
        foreground: '#e5eefc',
        cursor: '#0071e3',
        selectionBackground: '#1d3a5c',
      },
    });
    const fitAddon = new FitAddon();
    terminalRef.current = terminal;
    fitAddonRef.current = fitAddon;
    terminal.loadAddon(fitAddon);
    terminal.open(containerRef.current);
    terminal.focus();

    const socket = new WebSocket(resolveWebSocketUrl(terminalWsUrl));
    socketRef.current = socket;
    let disposed = false;
    let intentionalClose = false;

    const resizeDisposable = terminal.onResize(({ cols, rows }) => {
      sendJsonMessage({ type: 'resize', cols, rows });
    });

    const inputDisposable = isObserveOnly
      ? { dispose: () => {} }
      : terminal.onData((data) => {
          sendJsonMessage({ type: 'input', data });
        });

    socket.onopen = () => {
      if (disposed) {
        return;
      }
      setSocketStatus('connected');
      scheduleFitAndSendResize((payload) => {
        sendJsonMessage(payload);
      });
      queueMicrotask(() => {
        sendResizeAfterFit((payload) => {
          sendJsonMessage(payload);
        });
      });
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

        terminal.writeln('');
        terminal.writeln(
          translateRef.current('components.terminalConsole.exited', { code: payload.return_code })
        );
        setSocketStatus('disconnected');
        notifyDisconnected();
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
      if (!disposed && !intentionalClose) {
        setSocketStatus((current) => (current === 'connected' ? 'disconnected' : current));
        notifyDisconnected();
      }
    };

    return () => {
      disposed = true;
      intentionalClose = true;
      resizeDisposable.dispose();
      inputDisposable.dispose();
      socket.close();
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
      terminal.dispose();
      if (terminalRef.current === terminal) {
        terminalRef.current = null;
      }
      if (fitAddonRef.current === fitAddon) {
        fitAddonRef.current = null;
      }
      disconnectNotifiedRef.current = false;
    };
  }, [
    fontSize,
    isActive,
    isObserveOnly,
    notifyDisconnected,
    scheduleFitAndSendResize,
    sendJsonMessage,
    sendResizeAfterFit,
    sessionId,
    terminalWsUrl,
  ]);

  if (!isActive) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-6 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
        {placeholderText ?? t('components.terminalConsole.startPrompt')}
      </div>
    );
  }

  return (
    <section className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
            {isObserveOnly
              ? t('components.terminalConsole.observeOnly')
              : t('components.terminalConsole.writeEnabled')}
          </h3>
          <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('components.terminalConsole.websocketSession')}{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">
              {sessionId ?? 'n/a'}
            </code>
          </p>
          <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('components.terminalConsole.attachment')}{' '}
            <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">
              {attachmentId ?? 'n/a'}
            </code>
          </p>
          <p
            className={[
              'text-xs font-medium uppercase tracking-[0.08em]',
              isObserveOnly ? 'text-[#ff9500]' : 'text-[#34c759]',
            ].join(' ')}
          >
            {isObserveOnly
              ? t('components.terminalConsole.observeOnly')
              : t('components.terminalConsole.writeEnabled')}
          </p>
        </div>
        <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg)] px-3 py-1 text-xs font-medium text-[var(--text)]">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              displaySocketStatus === 'connected'
                ? 'bg-[#34c759]'
                : displaySocketStatus === 'error' || displaySocketStatus === 'disconnected'
                  ? 'bg-[#ff3b30]'
                  : 'bg-[#ff9500]'
            }`}
          />
          {t('components.terminalConsole.connection')} {connectionLabel[displaySocketStatus]}
        </div>
      </div>

      <div
        ref={containerRef}
        className="ainrf-terminal min-h-[480px] w-full overflow-hidden rounded-lg border border-[#1a1a2e] bg-[#0b1020]"
      />
    </section>
  );
}

export default TerminalSessionConsole;
