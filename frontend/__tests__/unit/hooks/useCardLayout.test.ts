import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCardLayout } from '../../../src/hooks/useCardLayout';

describe('useCardLayout', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns default layout on first mount', () => {
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['taskUsage', 'system', 'processes']);
  });

  it('swaps cards and persists to localStorage', () => {
    const { result } = renderHook(() => useCardLayout());
    act(() => {
      result.current.swapCards('taskUsage', 'system');
    });
    expect(result.current.layout.cardOrder).toEqual(['system', 'taskUsage', 'processes']);
    const stored = window.localStorage.getItem('scholar-agent:resources-layout');
    expect(JSON.parse(stored!).cardOrder).toEqual(['system', 'taskUsage', 'processes']);
  });

  it('falls back to default when localStorage is corrupted', () => {
    window.localStorage.setItem('scholar-agent:resources-layout', 'not-json');
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['taskUsage', 'system', 'processes']);
  });

  it('migrates old stored layouts by appending missing task usage card', () => {
    window.localStorage.setItem('scholar-agent:resources-layout', JSON.stringify({ cardOrder: ['system', 'processes'] }));
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['system', 'processes', 'taskUsage']);
  });
});
