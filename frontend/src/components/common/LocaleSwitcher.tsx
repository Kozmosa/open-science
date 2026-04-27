import { Globe } from 'lucide-react';
import { useLocaleSwitcher, useT } from '../../i18n';

function LocaleSwitcher() {
  const t = useT();
  const { locale, setLocale } = useLocaleSwitcher();

  return (
    <div
      data-testid="locale-switcher"
      className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--muted)] px-2 py-1"
    >
      <Globe size={14} className="text-[var(--muted-foreground)]" />
      <span className="sr-only">{t('common.language')}</span>
      <button
        type="button"
        onClick={() => setLocale('en')}
        aria-pressed={locale === 'en'}
        className={[
          'rounded-md px-2.5 py-1 text-xs font-medium transition',
          locale === 'en'
            ? 'bg-[var(--card)] text-[var(--foreground)] shadow-[var(--shadow-input)]'
            : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
        ].join(' ')}
      >
        {t('common.english')}
      </button>
      <button
        type="button"
        onClick={() => setLocale('zh')}
        aria-pressed={locale === 'zh'}
        className={[
          'rounded-md px-2.5 py-1 text-xs font-medium transition',
          locale === 'zh'
            ? 'bg-[var(--card)] text-[var(--foreground)] shadow-[var(--shadow-input)]'
            : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]',
        ].join(' ')}
      >
        {t('common.chinese')}
      </button>
    </div>
  );
}

export default LocaleSwitcher;
