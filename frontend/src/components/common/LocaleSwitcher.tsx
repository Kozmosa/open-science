import { Globe } from 'lucide-react';
import { useLocaleSwitcher, useT } from '../../i18n';

function LocaleSwitcher() {
  const t = useT();
  const { locale, setLocale } = useLocaleSwitcher();

  return (
    <div className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-2 py-1">
      <Globe size={14} className="text-white/50" />
      <span className="sr-only">{t('common.language')}</span>
      <button
        type="button"
        onClick={() => setLocale('en')}
        aria-pressed={locale === 'en'}
        className={[
          'rounded-md px-2.5 py-1 text-xs font-medium transition',
          locale === 'en'
            ? 'bg-white/20 text-white'
            : 'text-white/60 hover:text-white',
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
            ? 'bg-white/20 text-white'
            : 'text-white/60 hover:text-white',
        ].join(' ')}
      >
        {t('common.chinese')}
      </button>
    </div>
  );
}

export default LocaleSwitcher;
