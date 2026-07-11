# PromQL TextMate grammar

`promql.tmLanguage.json` is a mechanically converted copy of the PromQL TextMate grammar maintained by the Prometheus Community:

- Repository: <https://github.com/prometheus-community/vscode-promql>
- Pinned commit: [`adf638670578efeb9a52bd74465b5fa29af39ac9`](https://github.com/prometheus-community/vscode-promql/commit/adf638670578efeb9a52bd74465b5fa29af39ac9)
- Upstream source: `syntaxes/promql.tmlanguage.yml`
- Conversion: `js-yaml` YAML-to-JSON conversion, with no semantic grammar changes
- License: Apache License 2.0; see `LICENSE-vscode-promql.txt`

`promql.mjs` adds the Shiki registration name and aliases at load time so the
vendored JSON stays equivalent to the pinned upstream grammar. The same module
is used by Starlight and the fixed-fixture grammar regression check.
