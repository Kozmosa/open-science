/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { messages, type Locale, type MessageKey } from './messages';

const localeStorageKey = 'scholar-agent:locale';

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  toggleLocale: () => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
}

interface ProviderProps {
  children: ReactNode;
  initialLocale?: Locale;
}

function isLocale(value: string | null | undefined): value is Locale {
  return value === 'en' || value === 'zh';
}

function readStoredLocale(): Locale | null {
  try {
    const stored = window.localStorage.getItem(localeStorageKey);
    return isLocale(stored) ? stored : null;
  } catch {
    return null;
  }
}

function detectBrowserLocale(): Locale {
  const preferred = window.navigator.languages?.[0] ?? window.navigator.language ?? '';
  return preferred.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

function resolveInitialLocale(initialLocale?: Locale): Locale {
  return initialLocale ?? readStoredLocale() ?? detectBrowserLocale();
}

function readMessage(locale: Locale, key: MessageKey): string {
  const segments = key.split('.');
  let current: string | Record<string, unknown> | undefined = messages[locale];

  for (const segment of segments) {
    if (!current || typeof current !== 'object') {
      return key;
    }

    current = (current as Record<string, unknown>)[segment] as
      | string
      | Record<string, unknown>
      | undefined;
  }

  return typeof current === 'string' ? current : key;
}

function interpolate(template: string, values?: Record<string, string | number>): string {
  if (!values) {
    return template;
  }

  return template.replace(/\{\{(\w+)\}\}/g, (_, token: string) => {
    const value = values[token];
    return value === undefined ? '' : String(value);
  });
}

const defaultContextValue: I18nContextValue = {
  locale: 'en',
  setLocale: () => {},
  toggleLocale: () => {},
  t: (key, values) => interpolate(readMessage('en', key), values),
};

export const I18nContext = createContext<I18nContextValue>(defaultContextValue);

export function LocaleProvider({ children, initialLocale }: ProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(() => resolveInitialLocale(initialLocale));

  useEffect(() => {
    try {
      window.localStorage.setItem(localeStorageKey, locale);
    } catch {
      // Ignore storage failures and keep the locale in memory.
    }
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  }, [locale]);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
  }, []);

  const toggleLocale = useCallback(() => {
    setLocaleState((current) => (current === 'en' ? 'zh' : 'en'));
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale,
      toggleLocale,
      t: (key, values) => interpolate(readMessage(locale, key), values),
    }),
    [locale, setLocale, toggleLocale]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}

export function useLocale(): Locale {
  return useI18n().locale;
}

export function useT(): I18nContextValue['t'] {
  return useI18n().t;
}

export function useLocaleSwitcher(): Pick<I18nContextValue, 'locale' | 'setLocale' | 'toggleLocale'> {
  const { locale, setLocale, toggleLocale } = useI18n();
  return { locale, setLocale, toggleLocale };
}

export { messages };
export type { Locale } from './messages';
