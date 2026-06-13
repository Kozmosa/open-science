import { marked } from 'marked';
import { memo, useEffect, useRef, useState } from 'react';
import { workspaceFileBrowserHref } from '../../utils/workspaceFileLinks';

/** Parse markdown into HTML, rewriting workspace file links (absolute paths under
 *  `/.ainrf_workspaces/<slug>/...`) into in-app file-browser routes so assistant /
 *  tool-result links open the workspace browser instead of a raw filesystem path. */
function renderMarkdown(content: string): string {
  return marked.parse(content, {
    async: false,
    walkTokens(token) {
      if (token.type === 'link' && typeof token.href === 'string') {
        const rewritten = workspaceFileBrowserHref(token.href);
        if (rewritten) token.href = rewritten;
      }
    },
  }) as string;
}

const PROSE_STYLES =
  'prose-sm [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-semibold [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:my-0.5 [&_code]:rounded [&_code]:bg-[var(--bg-tertiary)] [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_pre]:my-1 [&_pre]:rounded-lg [&_pre]:bg-[var(--bg-tertiary)] [&_pre]:p-2 [&_blockquote]:my-1 [&_blockquote]:border-l-2 [&_blockquote]:border-[var(--text-tertiary)] [&_blockquote]:pl-3 [&_blockquote]:text-[var(--text-secondary)] [&_a]:text-[var(--apple-blue)] [&_a]:underline [&_strong]:font-semibold [&_em]:italic [&_hr]:my-2 [&_hr]:border-[var(--border)] [&_table]:my-1 [&_table]:w-full [&_th]:border [&_th]:border-[var(--border)] [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-[var(--border)] [&_td]:px-2 [&_td]:py-1';

interface SafeMarkdownProps {
  content: string;
  className?: string;
}

const SafeMarkdown = memo(function SafeMarkdown({ content, className = '' }: SafeMarkdownProps) {
  // Debounce markdown parsing: during streaming, deltas arrive every ~5ms.
  // Parsing on every delta is wasteful — batch them with a short delay.
  const [parsedHtml, setParsedHtml] = useState(() => renderMarkdown(content));
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setParsedHtml(renderMarkdown(content));
    }, 80);
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, [content]);

  return (
    <div
      className={`break-words font-sans text-sm [&_p]:whitespace-pre-wrap ${PROSE_STYLES} ${className}`}
      dangerouslySetInnerHTML={{ __html: parsedHtml }}
    />
  );
});

export default SafeMarkdown;
