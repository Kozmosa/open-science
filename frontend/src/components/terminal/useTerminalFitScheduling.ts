import { useCallback, useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import type { FitAddon } from '@xterm/addon-fit';
import type { Terminal } from 'xterm';

type ResizeMessage = { type: 'resize'; cols: number; rows: number };

function scheduleAnimationFrame(callback: () => void): () => void {
  if (typeof window.requestAnimationFrame === 'function') {
    const frameId = window.requestAnimationFrame(callback);
    return () => window.cancelAnimationFrame(frameId);
  }

  const timeoutId = window.setTimeout(callback, 0);
  return () => window.clearTimeout(timeoutId);
}

function scheduleTimeout(callback: () => void, delay: number): () => void {
  const timeoutId = window.setTimeout(callback, delay);
  return () => window.clearTimeout(timeoutId);
}

interface UseTerminalFitSchedulingOptions {
  active: boolean;
  containerRef: RefObject<HTMLDivElement | null>;
  fitAddonRef: RefObject<FitAddon | null>;
  terminalRef: RefObject<Terminal | null>;
}

interface UseTerminalFitSchedulingResult {
  scheduleFit: () => void;
  scheduleFitAndSendResize: (sendResize: (payload: ResizeMessage) => void) => void;
  sendResizeAfterFit: (sendResize: (payload: ResizeMessage) => void) => void;
}

export function useTerminalFitScheduling({
  active,
  containerRef,
  fitAddonRef,
  terminalRef,
}: UseTerminalFitSchedulingOptions): UseTerminalFitSchedulingResult {
  const stateRef = useRef<{
    disposed: boolean;
    scheduleToken: number;
    cancelScheduledFits: Array<() => void>;
  }>({
    disposed: false,
    scheduleToken: 0,
    cancelScheduledFits: [],
  });

  const fitTerminal = useCallback(() => {
    const fitAddon = fitAddonRef.current;
    if (!fitAddon) {
      return;
    }

    try {
      fitAddon.fit();
    } catch {
      // ignore fit failures while the container is hidden or resizing
    }
  }, [fitAddonRef]);

  const scheduleFit = useCallback(() => {
    const nextToken = stateRef.current.scheduleToken + 1;
    stateRef.current.scheduleToken = nextToken;

    for (const cancel of stateRef.current.cancelScheduledFits) {
      cancel();
    }
    stateRef.current.cancelScheduledFits = [];

    const runIfCurrent = (callback: () => void) => {
      if (stateRef.current.disposed || stateRef.current.scheduleToken !== nextToken) {
        return;
      }
      callback();
    };

    const runFit = () => {
      runIfCurrent(() => {
        fitTerminal();
      });
    };

    // xterm measures after open(), but font and layout changes can settle later, so delayed retries keep terminal sizing stable.
    stateRef.current.cancelScheduledFits.push(scheduleAnimationFrame(runFit));
    stateRef.current.cancelScheduledFits.push(
      scheduleAnimationFrame(() => {
        runIfCurrent(() => {
          stateRef.current.cancelScheduledFits.push(scheduleAnimationFrame(runFit));
        });
      })
    );
    stateRef.current.cancelScheduledFits.push(scheduleTimeout(runFit, 80));
    if (typeof document.fonts?.ready?.then === 'function') {
      void document.fonts.ready.then(runFit).catch(() => {});
    }
  }, [fitTerminal]);

  const fitAndSendResize = useCallback(
    (sendResize: (payload: ResizeMessage) => void) => {
      const terminal = terminalRef.current;
      if (stateRef.current.disposed || !terminal) {
        return;
      }

      fitTerminal();
      sendResize({ type: 'resize', cols: terminal.cols, rows: terminal.rows });
    },
    [fitTerminal, terminalRef]
  );

  const scheduleFitAndSendResize = useCallback(
    (sendResize: (payload: ResizeMessage) => void) => {
      scheduleFit();
      const scheduledToken = stateRef.current.scheduleToken;
      stateRef.current.cancelScheduledFits.push(
        scheduleTimeout(() => {
          if (stateRef.current.disposed || stateRef.current.scheduleToken !== scheduledToken) {
            return;
          }
          fitAndSendResize(sendResize);
        }, 120)
      );
    },
    [fitAndSendResize, scheduleFit]
  );

  const sendResizeAfterFit = useCallback(
    (sendResize: (payload: ResizeMessage) => void) => {
      const scheduledToken = stateRef.current.scheduleToken;
      stateRef.current.cancelScheduledFits.push(
        scheduleAnimationFrame(() => {
          if (stateRef.current.disposed || stateRef.current.scheduleToken !== scheduledToken) {
            return;
          }
          fitAndSendResize(sendResize);
        })
      );
    },
    [fitAndSendResize]
  );

  useEffect(() => {
    stateRef.current.disposed = !active;
    const currentState = stateRef.current;

    const container = containerRef.current;

    if (!active || !container) {
      return undefined;
    }

    const handleWindowResize = () => {
      scheduleFit();
    };

    const resizeObserver =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            scheduleFit();
          });

    resizeObserver?.observe(container);
    window.addEventListener('resize', handleWindowResize);
    scheduleFit();
    const cancelDeferredFit = scheduleAnimationFrame(() => {
      scheduleFit();
    });

    return () => {
      currentState.disposed = true;
      currentState.scheduleToken += 1;
      cancelDeferredFit();
      for (const cancel of currentState.cancelScheduledFits) {
        cancel();
      }
      currentState.cancelScheduledFits = [];
      resizeObserver?.disconnect();
      window.removeEventListener('resize', handleWindowResize);
    };
  }, [active, containerRef, scheduleFit]);

  return {
    scheduleFit,
    scheduleFitAndSendResize,
    sendResizeAfterFit,
  };
}
