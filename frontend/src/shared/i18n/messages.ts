export type Locale = 'en' | 'zh';

type MessageTree = {
  [key: string]: string | MessageTree;
};

type Paths<T, Prefix extends string = ''> = T extends string
  ? never
  : {
      [Key in Extract<keyof T, string>]: T[Key] extends string
        ? Prefix extends ''
          ? Key
          : `${Prefix}.${Key}`
        : T[Key] extends MessageTree
          ? Paths<T[Key], Prefix extends '' ? Key : `${Prefix}.${Key}`>
          : never;
    }[Extract<keyof T, string>];

import { messages } from './catalog';

export { messages };
export type MessageKey = Paths<(typeof messages)['en']>;
