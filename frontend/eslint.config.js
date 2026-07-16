import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', 'dist-mock', 'public/mockServiceWorker.js']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    files: ['src/**/*.{ts,tsx}', '__tests__/**/*.{ts,tsx}'],
    ignores: ['src/design-system/**/*'],
    rules: {
      'no-restricted-imports': ['error', {
        patterns: [
          {
            group: ['@design-system/*'],
            message: 'Import product UI contracts from the public @design-system barrel.',
          },
          {
            group: ['@radix-ui/*'],
            message: 'Radix is an internal design-system implementation detail.',
          },
          {
            group: ['@/components/ui', '@/components/ui/*', '**/components/ui', '**/components/ui/*'],
            message: 'Legacy components/ui imports are forbidden; use @design-system.',
          },
        ],
      }],
    },
  },
])
