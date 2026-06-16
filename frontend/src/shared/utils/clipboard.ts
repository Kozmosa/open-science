/**
 * Robust cross-browser copy-to-clipboard helper.
 *
 * `navigator.clipboard.writeText()` is the modern API, but it can fail in:
 *   - non-secure contexts (HTTP)
 *   - cross-origin iframes
 *   - browsers that deny the transient user-gesture permission
 *
 * This helper falls back to the deprecated `document.execCommand('copy')`
 * technique, which still works in most environments where the Clipboard API
 * is restricted.
 */

export interface CopyResult {
  success: boolean;
  error?: Error;
}

async function copyWithClipboardAPI(text: string): Promise<boolean> {
  if (!navigator.clipboard || !navigator.clipboard.writeText) {
    return false;
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function copyWithExecCommand(text: string): boolean {
  const previousActiveElement = document.activeElement;

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '-9999px';
  textarea.style.opacity = '0';
  textarea.setAttribute('aria-hidden', 'true');
  document.body.appendChild(textarea);

  textarea.focus();
  textarea.select();

  let success = false;
  try {
    success = document.execCommand('copy');
  } catch {
    success = false;
  }

  document.body.removeChild(textarea);

  // Restore focus so keyboard users don't lose their place.
  if (previousActiveElement instanceof HTMLElement) {
    previousActiveElement.focus();
  }

  return success;
}

/**
 * Copy *text* to the clipboard.
 *
 * Returns `{ success: true }` on success, or `{ success: false, error }`
 * when neither the Clipboard API nor the execCommand fallback succeeded.
 */
export async function copyText(text: string): Promise<CopyResult> {
  if (text === '') {
    // Copying an empty string is technically valid, but it is almost never
    // what the user intended. Treat it as a failure so the UI can show a hint.
    return { success: false, error: new Error('Nothing to copy') };
  }

  if (await copyWithClipboardAPI(text)) {
    return { success: true };
  }

  if (copyWithExecCommand(text)) {
    return { success: true };
  }

  return {
    success: false,
    error: new Error('Clipboard access was denied or is unavailable'),
  };
}
