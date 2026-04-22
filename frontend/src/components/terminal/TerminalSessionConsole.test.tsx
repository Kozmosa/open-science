import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TerminalSessionConsole from './TerminalSessionConsole';
import type { TerminalSessionStatus } from '../../types';

interface MockTerminalInstance {
  cols: number;
  rows: number;
  readonly dataHandlers: Array<(data: string) => void>;
  readonly resizeHandlers: Array<(size: { cols: number; rows: number }) => void>;
  readonly writeCalls: string[];
  readonly writelnCalls: string[];
  container: HTMLDivElement | null;
  disposed: boolean;
  loadAddon(addon: MockFitAddonInstance): void;
  open(container: HTMLDivElement): void;
  focus(): void;
  write(value: string): void;
  writeln(value: string): void;
  dispose(): void;
  onData(handler: (data: string) => void): { dispose: () => void };
  onResize(handler: (size: { cols: number; rows: number }) => void): { dispose: () => void };
  emitData(data: string): void;
  emitResize(cols: number, rows: number): void;
}

interface MockFitAddonInstance {
  terminal: MockTerminalInstance | null;
  readonly fitCalls: number[];
  bindTerminal(terminal: MockTerminalInstance): void;
  fit(): void;
}

interface MockWebSocketInstance {
  readonly url: string;
  readonly sent: string[];
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  send(data: string): void;
  close(): void;
  emitMessage(data: unknown): void;
}

const terminalMocks = vi.hoisted(() => ({
  terminals: [] as MockTerminalInstance[],
  fitAddons: [] as MockFitAddonInstance[],
  sockets: [] as MockWebSocketInstance[],
  MockTerminal: class MockTerminal implements MockTerminalInstance {
    cols = 80;
    rows = 24;
    container: HTMLDivElement | null = null;
    readonly dataHandlers: Array<(data: string) => void> = [];
    readonly resizeHandlers: Array<(size: { cols: number; rows: number }) => void> = [];
    readonly writeCalls: string[] = [];
    readonly writelnCalls: string[] = [];
    disposed = false;

    constructor() {
      terminalMocks.terminals.push(this);
    }

    loadAddon(addon: MockFitAddonInstance): void {
      addon.bindTerminal(this);
    }

    open(container: HTMLDivElement): void {
      this.container = container;
    }

    focus(): void {}

    write(value: string): void {
      this.writeCalls.push(value);
    }

    writeln(value: string): void {
      this.writelnCalls.push(value);
    }

    dispose(): void {
      this.disposed = true;
    }

    onData(handler: (data: string) => void): { dispose: () => void } {
      this.dataHandlers.push(handler);
      return {
        dispose: () => {
          const index = this.dataHandlers.indexOf(handler);
          if (index >= 0) {
            this.dataHandlers.splice(index, 1);
          }
        },
      };
    }

    onResize(handler: (size: { cols: number; rows: number }) => void): { dispose: () => void } {
      this.resizeHandlers.push(handler);
      return {
        dispose: () => {
          const index = this.resizeHandlers.indexOf(handler);
          if (index >= 0) {
            this.resizeHandlers.splice(index, 1);
          }
        },
      };
    }

    emitData(data: string): void {
      for (const handler of this.dataHandlers) {
        handler(data);
      }
    }

    emitResize(cols: number, rows: number): void {
      this.cols = cols;
      this.rows = rows;
      for (const handler of this.resizeHandlers) {
        handler({ cols, rows });
      }
    }
  },
  MockFitAddon: class MockFitAddon implements MockFitAddonInstance {
    terminal: MockTerminalInstance | null = null;
    readonly fitCalls: number[] = [];

    constructor() {
      terminalMocks.fitAddons.push(this);
    }

    bindTerminal(terminal: MockTerminalInstance): void {
      this.terminal = terminal;
    }

    fit(): void {
      this.fitCalls.push(Date.now());
      this.terminal?.emitResize(100, 30);
    }
  },
  MockWebSocket: class MockWebSocket implements MockWebSocketInstance {
    static readonly CONNECTING = WebSocket.CONNECTING;
    static readonly OPEN = WebSocket.OPEN;
    static readonly CLOSING = WebSocket.CLOSING;
    static readonly CLOSED = WebSocket.CLOSED;

    readonly url: string;
    readonly sent: string[] = [];
    readyState: number = WebSocket.CONNECTING;
    onopen: ((event: Event) => void) | null = null;
    onmessage: ((event: MessageEvent<string>) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    onclose: ((event: CloseEvent) => void) | null = null;

    constructor(url: string) {
      this.url = url;
      terminalMocks.sockets.push(this);
      queueMicrotask(() => {
        this.readyState = WebSocket.OPEN;
        this.onopen?.(new Event('open'));
      });
    }

    send(data: string): void {
      this.sent.push(data);
    }

    close(): void {
      if (this.readyState === WebSocket.CLOSED) {
        return;
      }
      this.readyState = WebSocket.CLOSED;
      this.onclose?.(new CloseEvent('close'));
    }

    emitMessage(data: unknown): void {
      this.onmessage?.(
        new MessageEvent('message', {
          data: typeof data === 'string' ? data : JSON.stringify(data),
        })
      );
    }
  },
}));

vi.mock('xterm', () => ({
  Terminal: terminalMocks.MockTerminal,
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: terminalMocks.MockFitAddon,
}));

const nativeWebSocket = window.WebSocket;
vi.stubGlobal('WebSocket', terminalMocks.MockWebSocket);

beforeEach(() => {
  Object.defineProperty(window, 'WebSocket', {
    configurable: true,
    value: terminalMocks.MockWebSocket,
  });
  terminalMocks.terminals.length = 0;
  terminalMocks.fitAddons.length = 0;
  terminalMocks.sockets.length = 0;
});

afterEach(() => {
  Object.defineProperty(window, 'WebSocket', {
    configurable: true,
    value: nativeWebSocket,
  });
  vi.clearAllMocks();
});

function renderConsole(status: TerminalSessionStatus = 'running') {
  return render(
    <TerminalSessionConsole
      sessionId="ainrf:u:mock-browser-user:e:env-1:personal"
      attachmentId="attach-1"
      terminalWsUrl="ws://127.0.0.1:8000/terminal/attachments/attach-1/ws?token=test-token"
      status={status}
      onDisconnected={vi.fn()}
    />
  );
}

describe('TerminalSessionConsole', () => {
  it('connects to the websocket, writes output, and forwards input', async () => {
    const onDisconnected = vi.fn();

    render(
      <TerminalSessionConsole
        sessionId="ainrf:u:mock-browser-user:e:env-1:personal"
        attachmentId="attach-1"
        terminalWsUrl="ws://127.0.0.1:8000/terminal/attachments/attach-1/ws?token=test-token"
        status="running"
        onDisconnected={onDisconnected}
      />
    );

    await waitFor(() => expect(terminalMocks.sockets).toHaveLength(1));

    const socket = terminalMocks.sockets[0];
    const terminal = terminalMocks.terminals[0];

    expect(socket.url).toBe(
      'ws://127.0.0.1:8000/terminal/attachments/attach-1/ws?token=test-token'
    );
    socket.onopen?.(new Event('open'));
    await waitFor(() => expect(screen.getByText('Connection: connected')).toBeInTheDocument());
    expect(socket.sent[0]).toBe(JSON.stringify({ type: 'resize', cols: 100, rows: 30 }));
    expect(socket.sent[1]).toBe(JSON.stringify({ type: 'resize', cols: 100, rows: 30 }));

    terminal.emitData('ls\n');
    expect(socket.sent).toContain(JSON.stringify({ type: 'input', data: 'ls\n' }));

    socket.emitMessage({ type: 'output', data: 'hello\n' });
    expect(terminal.writeCalls).toContain('hello\n');

    socket.emitMessage({ type: 'status', status: 'exited', return_code: 0 });
    expect(terminal.writelnCalls).toContain('Session exited with code 0');
    expect(onDisconnected).toHaveBeenCalledTimes(1);
  });

  it('renders a placeholder when the session is not running', () => {
    renderConsole('idle');

    expect(screen.getByText('Attach to a personal terminal session to open the xterm console.')).toBeInTheDocument();
  });

  it('keeps observe attachments readonly while still forwarding resize events', async () => {
    render(
      <TerminalSessionConsole
        sessionId="ainrf:u:mock-browser-user:e:env-1:agent"
        attachmentId="attach-task-1"
        terminalWsUrl="ws://127.0.0.1:8000/terminal/attachments/attach-task-1/ws?token=test-token"
        status="running"
        readonly
        mode="observe"
      />
    );

    await waitFor(() => expect(terminalMocks.sockets).toHaveLength(1));

    const socket = terminalMocks.sockets[0];
    const terminal = terminalMocks.terminals[0];
    socket.onopen?.(new Event('open'));
    terminal.emitData('ignored input');

    expect(
      socket.sent.every((message) => JSON.parse(message).type === 'resize')
    ).toBe(true);
    expect(socket.sent.length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Observe-only')).toHaveLength(2);
  });
});
