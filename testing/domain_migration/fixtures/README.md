# Domain migration fixtures

These fixtures are synthetic, versioned legacy state roots for S0/B2 migration tests. They must never contain tenant credentials, real paths, or exported production state.

- `normal`: mappable Project and Workspace records.
- `empty`: valid empty registry inputs.
- `missing-fields`: malformed ownership input.
- `duplicate-path`: two legacy workspaces with the same canonical location.
- `owner-anomaly`: a literal legacy administrator owner that cannot be mapped.
- `unmapped-session`: legacy session data with no Task mapping.
