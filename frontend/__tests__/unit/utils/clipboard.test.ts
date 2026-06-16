import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { copyText } from '../../../src/shared/utils/clipboard';

describe('copyText', () => {
  let execCommandSpy: ReturnType<typeof vi.spyOn>;
  let clipboardWriteText: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // jsdom does not implement document.execCommand, so attach a mock
    // directly to the document object before spying on it.
    const execCommandMock = vi.fn().mockReturnValue(true);
    (document as Document & { execCommand: typeof execCommandMock }).execCommand = execCommandMock;
    execCommandSpy = vi.spyOn(
      document as Document & { execCommand: typeof execCommandMock },
      'execCommand'
    ).mockReturnValue(true);

    clipboardWriteText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: clipboardWriteText },
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uses navigator.clipboard.writeText when available', async () => {
    const result = await copyText('hello');
    expect(result.success).toBe(true);
    expect(clipboardWriteText).toHaveBeenCalledWith('hello');
    expect(execCommandSpy).not.toHaveBeenCalled();
  });

  it('falls back to document.execCommand when clipboard API is unavailable', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true,
    });

    const result = await copyText('fallback');
    expect(result.success).toBe(true);
    expect(execCommandSpy).toHaveBeenCalledWith('copy');
  });

  it('falls back to document.execCommand when clipboard API throws', async () => {
    clipboardWriteText.mockRejectedValue(new Error('denied'));

    const result = await copyText('fallback after error');
    expect(result.success).toBe(true);
    expect(execCommandSpy).toHaveBeenCalledWith('copy');
  });

  it('returns failure when both mechanisms fail', async () => {
    clipboardWriteText.mockRejectedValue(new Error('denied'));
    execCommandSpy.mockReturnValue(false);

    const result = await copyText('both fail');
    expect(result.success).toBe(false);
    expect(result.error).toBeInstanceOf(Error);
  });

  it('returns failure for empty strings', async () => {
    const result = await copyText('');
    expect(result.success).toBe(false);
    expect(clipboardWriteText).not.toHaveBeenCalled();
    expect(execCommandSpy).not.toHaveBeenCalled();
  });

  it('cleans up the temporary textarea after copying', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true,
    });

    const initialBodyChildCount = document.body.children.length;
    await copyText('cleanup check');
    expect(document.body.children.length).toBe(initialBodyChildCount);
  });
});
