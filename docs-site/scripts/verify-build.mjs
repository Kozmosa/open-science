import { readFile } from 'node:fs/promises';
import { createHighlighter } from 'shiki';
import promqlLanguage from '../src/languages/promql.mjs';

const metricsPage = new URL(
  '../dist/observability/metrics/index.html',
  import.meta.url,
);
const notFoundPage = new URL('../dist/404.html', import.meta.url);
const [html, notFoundHtml] = await Promise.all([
  readFile(metricsPage, 'utf8'),
  readFile(notFoundPage, 'utf8'),
]);
const languageMarker = 'data-language="promql"';

if (!html.includes(languageMarker)) {
  throw new Error(
    `Missing ${languageMarker} in ${metricsPage.pathname}; PromQL grammar registration may be broken.`,
  );
}

if (!notFoundHtml.includes('页面未找到')) {
  throw new Error(`Custom documentation 404 page was not rendered at ${notFoundPage.pathname}.`);
}

const fixture = `# HTTP 5xx error rate
sum by (status) (rate(http_requests_total{status=~"5.."}[5m])) > 0.1`;
const highlighter = await createHighlighter({
  themes: ['github-dark'],
  langs: [promqlLanguage],
});

try {
  const result = highlighter.codeToTokens(fixture, {
    lang: 'promql',
    theme: 'github-dark',
  });
  const highlightedTokens = result.tokens
    .flat()
    .filter((token) => token.content.trim().length > 0 && token.color);
  const distinctTokenColors = new Set(highlightedTokens.map((token) => token.color));

  if (highlightedTokens.length < 12 || distinctTokenColors.size < 5) {
    throw new Error(
      'PromQL grammar did not produce the expected token and color diversity for the fixed fixture.',
    );
  }

  console.log(
    `Verified PromQL syntax highlighting (${highlightedTokens.length} fixture tokens, ` +
      `${distinctTokenColors.size} colors).`,
  );
} finally {
  highlighter.dispose();
}
