import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useCardLayout } from './useCardLayout';

describe('useCardLayout', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('returns default layout on first mount', () => {
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['system', 'processes']);
  });

  it('swaps cards and persists to localStorage', () => {
    const { result } = renderHook(() => useCardLayout());
    act(() => {
      result.current.swapCards('system', 'processes');
    });
    expect(result.current.layout.cardOrder).toEqual(['processes', 'system']);
    const stored = window.localStorage.getItem('scholar-agent:resources-layout');
    expect(JSON.parse(stored!).cardOrder).toEqual(['processes', 'system']);
  });

  it('falls back to default when localStorage is corrupted', () => {
    window.localStorage.setItem('scholar-agent:resources-layout', 'not-json');
    const { result } = renderHook(() => useCardLayout());
    expect(result.current.layout.cardOrder).toEqual(['system', 'processes']);
  });
});
