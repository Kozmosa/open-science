import { useState } from 'react';
import { useT } from '../../i18n';
import type { LiteraturePaper } from '../../types';
import { markPaperRead } from '../../api';

interface Props {
  paper: LiteraturePaper;
  onConvertToTask: (paperId: string) => void;
  onReadChange: () => void;
}

export default function PaperCard({ paper, onConvertToTask, onReadChange }: Props) {
  const t = useT();
  const [summaryOpen, setSummaryOpen] = useState(false);

  const handleMarkRead = async () => {
    try {
      await markPaperRead(paper.paper_id);
      onReadChange();
    } catch {
      // Silently handle error
    }
  };

  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 transition hover:shadow-sm">
      {/* Top row: category badge + published date */}
      <div className="mb-2 flex items-center justify-between">
        <span className="inline-block rounded-full bg-[var(--apple-blue)]/10 px-2 py-0.5 text-[11px] font-medium text-[var(--apple-blue)]">
          {paper.arxiv_category}
        </span>
        <span className="text-[11px] text-[var(--text-tertiary)]">
          {paper.published_at ? new Date(paper.published_at).toLocaleDateString() : ''}
        </span>
      </div>

      {/* Title */}
      <h3 className="text-sm font-semibold leading-snug text-[var(--foreground)]">
        {paper.title}
      </h3>
      {paper.title_zh && (
        <p className="mt-0.5 text-xs text-[var(--text-secondary)]">{paper.title_zh}</p>
      )}

      {/* Authors and journal */}
      <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
        {paper.authors.join(', ')}
        {paper.journal && <span className="ml-1 italic">{paper.journal}</span>}
      </p>

      {/* AI Practice Note */}
      {paper.ai_practice_note && (
        <div className="mt-3 border-l-4 border-[var(--apple-blue)] bg-[var(--apple-blue)]/5 pl-3">
          <p className="text-xs font-medium text-[var(--apple-blue)]">{t('literature.aiPracticeNote')}</p>
          <p className="mt-0.5 text-xs italic text-[var(--text-secondary)]">{paper.ai_practice_note}</p>
        </div>
      )}

      {/* AI Summary (collapsible) */}
      {paper.ai_summary && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setSummaryOpen(!summaryOpen)}
            className="flex items-center gap-1 text-xs font-medium text-[var(--apple-blue)] hover:underline"
          >
            <span className={summaryOpen ? 'rotate-90' : ''}>&#9654;</span>
            {t('literature.aiSummary')}
          </button>
          {summaryOpen && (
            <ul className="mt-2 space-y-1 pl-3">
              {paper.ai_summary.split('\n').filter(Boolean).map((line, i) => (
                <li key={i} className="text-xs leading-relaxed text-[var(--text-secondary)]">
                  {line.startsWith('- ') ? line : `- ${line}`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Action bar */}
      <div className="mt-3 flex items-center gap-2 border-t border-[var(--border)] pt-3">
        {!paper.is_read && (
          <button
            type="button"
            onClick={handleMarkRead}
            className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg)]"
          >
            {t('literature.markRead')}
          </button>
        )}
        <a
          href={`https://arxiv.org/abs/${paper.paper_id}`}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-md border border-[var(--border)] px-2.5 py-1 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg)]"
        >
          {t('literature.viewarXiv')}
        </a>
        <button
          type="button"
          onClick={() => onConvertToTask(paper.paper_id)}
          disabled={paper.is_converted_to_task}
          className="ml-auto rounded-md border border-[var(--apple-blue)]/30 px-2.5 py-1 text-[11px] text-[var(--apple-blue)] hover:bg-[var(--apple-blue)]/5 disabled:opacity-40"
        >
          {t('literature.convertToTask')}
        </button>
      </div>
    </div>
  );
}
