import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useResolvedOsciTheme } from '@/shared/hooks/useResolvedOsciTheme';

describe('useResolvedOsciTheme', () => {
  it('tracks the resolved osci theme mount point instead of the system preference', async () => {
    document.documentElement.dataset.osciTheme = 'light';
    const { result } = renderHook(() => useResolvedOsciTheme());
    expect(result.current).toBe('light');

    act(() => {
      document.documentElement.dataset.osciTheme = 'dark';
    });
    await waitFor(() => expect(result.current).toBe('dark'));
  });
});
