import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, renderHook } from '@testing-library/react';
import { LocaleProvider, resolveErrorCopy } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import { ApiError } from '@/shared/api/client';

describe('error code localization', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('resolves coded errors to localized copy under the zh locale', () => {
    const { result } = renderHook(() => resolveErrorCopy('project_publish_required'), {
      wrapper: ({ children }) => <LocaleProvider initialLocale="zh">{children}</LocaleProvider>,
    });
    // The provider mirrors the locale before this query runs.
    expect(result.current).toBe('需要项目发布权限。');
  });

  it('resolves coded errors to English copy under the en locale', () => {
    const { result } = renderHook(() => resolveErrorCopy('environment_alias_exists'), {
      wrapper: ({ children }) => <LocaleProvider initialLocale="en">{children}</LocaleProvider>,
    });
    expect(result.current).toBe('An environment with this alias already exists.');
  });

  it('returns null for an unmapped code so callers fall back', () => {
    const { result } = renderHook(() => resolveErrorCopy('future_unknown_code'), {
      wrapper: ({ children }) => <LocaleProvider initialLocale="zh">{children}</LocaleProvider>,
    });
    expect(result.current).toBeNull();
  });

  it('extractErrorMessage prefers localized copy for coded ApiErrors', () => {
    render(<LocaleProvider initialLocale="zh" />);
    const error = new ApiError('Project publish permission is required (HTTP 403)', 403, '/x', {
      detail: { code: 'project_publish_required', message: 'Project publish permission is required' },
    }, 'project_publish_required');
    expect(extractErrorMessage(error)).toBe('需要项目发布权限。');
  });

  it('extractErrorMessage falls back to the raw message for unmapped codes', () => {
    render(<LocaleProvider initialLocale="zh" />);
    const error = new ApiError('Something internal broke (HTTP 500)', 500, '/x', undefined, 'unmapped_code');
    expect(extractErrorMessage(error)).toBe('Something internal broke (HTTP 500)');
  });

  it('keeps plain Error messages untouched', () => {
    render(<LocaleProvider initialLocale="zh" />);
    expect(extractErrorMessage(new Error('network offline'))).toBe('network offline');
    expect(extractErrorMessage('raw string')).toBe('raw string');
    expect(extractErrorMessage(undefined)).toBeNull();
  });
});
