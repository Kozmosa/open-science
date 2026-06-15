// i18n message catalog — aggregates feature-localized modules per locale
import * as en from './en';
import * as zh from './zh';

export const messages = {
  en: {
    ...en.common,
    ...en.auth,
    ...en.navigation,
    ...en.pages,
    ...en.components,
  },
  zh: {
    ...zh.common,
    ...zh.auth,
    ...zh.navigation,
    ...zh.pages,
    ...zh.components,
  },
};
