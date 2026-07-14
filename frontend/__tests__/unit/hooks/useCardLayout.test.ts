import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useCardLayout } from '../../../src/hooks/useCardLayout';

describe('useCardLayout', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns default layout on first mount', () => {
    const { result } = renderHook(() => useCardLayout('user-1'));
    expect(result.current.layout.cardOrder).toEqual(['taskUsage', 'system', 'processes']);
  });

  it('swaps cards and persists to localStorage', () => {
    const { result } = renderHook(() => useCardLayout('user-1'));
    act(() => {
      result.current.swapCards('taskUsage', 'system');
    });
    expect(result.current.layout.cardOrder).toEqual(['system', 'taskUsage', 'processes']);
    const stored = window.localStorage.getItem('openscience:preference:user-1:resources-card-layout');
    expect(JSON.parse(stored!).cardOrder).toEqual(['system', 'taskUsage', 'processes']);
  });

  it('isolates card order by user id', () => {
    const first = renderHook(() => useCardLayout('user-1'));
    act(() => first.result.current.swapCards('taskUsage', 'system'));
    first.unmount();

    const second = renderHook(() => useCardLayout('user-2'));
    expect(second.result.current.layout.cardOrder).toEqual(['taskUsage', 'system', 'processes']);
  });

  it('falls back to default when localStorage is corrupted', () => {
    window.localStorage.setItem('openscience:resources-layout', 'not-json');
    const { result } = renderHook(() => useCardLayout('user-1'));
    expect(result.current.layout.cardOrder).toEqual(['taskUsage', 'system', 'processes']);
  });

  it('migrates old stored layouts by appending missing task usage card', async () => {
    window.localStorage.setItem('scholar-agent:resources-layout', JSON.stringify({ cardOrder: ['system', 'processes'] }));
    const { result } = renderHook(() => useCardLayout('user-1'));
    await waitFor(() => expect(result.current.layout.cardOrder).toEqual(['system', 'processes', 'taskUsage']));
    expect(window.localStorage.getItem('openscience:preference:user-1:resources-card-layout')).not.toBeNull();
    expect(window.localStorage.getItem('scholar-agent:resources-layout')).toBeNull();
  });
});
