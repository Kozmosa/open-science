# Isolated domain L2 recovery cell

`run_cell.sh` is a trusted-maintainer integration harness for the recovery
scenarios that cannot be proved in the deterministic L0/L1 process.  It is
not staging, does not reuse shared Docker resources, and is deliberately
non-executing by default.

The default command only validates the static Compose contract, creates a
unique cell plan, and writes a redacted evidence manifest outside every Git
worktree and the shared Git directory:

```bash
OPENSCIENCE_L2_BACKEND_IMAGE_DIGEST='registry.example/openscience@sha256:...' \
OPENSCIENCE_L2_SCENARIO_IMAGE_DIGEST='registry.example/openscience-l2-scenarios@sha256:...' \
OPENSCIENCE_L2_PRIOR_FRONTEND_IMAGE_DIGEST='registry.example/openscience-frontend@sha256:...' \
OPENSCIENCE_L2_PRIOR_FRONTEND_ARTIFACT_SHA256='...' \
bash testing/domain_l2/run_cell.sh plan
```

Execution requires all of the following, so an accidental shell invocation
cannot select the default Docker daemon:

- the `execute` subcommand;
- `OPENSCIENCE_L2_EXECUTE=1`;
- `OPENSCIENCE_L2_DOCKER_CONTEXT` and `DOCKER_CONTEXT` set to the same
  `openscience-l2-*` context;
- `OPENSCIENCE_L2_CONTEXT_ACK=isolated`.

The context name is denylisted for `default`, production, staging, and shared
names.  Naming is not a substitute for operator verification: trusted
maintainers must provision that context with an isolated daemon before running
the harness.

The Compose template uses only cell-generated named volumes, loopback ports,
random credentials, and immutable image digests.  It contains no source bind
mount, Docker socket, `container_name`, production/staging `.env`, or host
runtime volume.  The harness deletes only its uniquely named cell resources on
completion, including if `compose up --wait` has already created partial
resources before reporting a failed health check.

The generated private runtime env writes identical `OPENSCIENCE_*` and
`AINRF_*` API-key/JWT aliases.  `ApiConfig` prefers the OpenScience names, but
the current CLI preflight and JWT helper still require the legacy names; both
must be present until those entrypoints are migrated.

The immutable scenario image must implement this command contract:

```text
/opt/openscience-l2/run-scenario <scenario> <phase>
```

It must also provide the immutable same-origin gateway contract used to run a
released frontend artifact against the candidate backend:

```text
/opt/openscience-l2/run-frontend-gateway \
  --listen 0.0.0.0:8080 \
  --frontend-upstream http://prior-frontend:80 \
  --api-upstream http://api:8000
```

The gateway must proxy the prior frontend assets and its relative `/api/*`
requests to the candidate API without a host bind mount.  It exposes
`/health`, and preserves `/.well-known/openscience-artifact.json` from the
frontend artifact.  That manifest must declare the exact SHA-256 supplied as
`OPENSCIENCE_L2_PRIOR_FRONTEND_ARTIFACT_SHA256`; the scenario runner must fail
if it is absent or mismatched.  This makes the old-client check a real
same-origin route test rather than a direct mocked API request.

It must fail if assertions are absent or skipped.  The harness never treats a
missing scenario implementation as a successful L2 result.  It invokes these
scenarios:

1. `backup-migration-restart-reconcile-restore`
2. `importer-crash-resume`
3. `double-dispatcher-claim-expiry`
4. `launch-after-crash`
5. `literature-saga-crash-recovery`
6. `prior-frontend-artifact-contract`

`literature-saga-crash-recovery` must crash after deterministic Task creation
and before the Literature link is finalized, restart the domain worker, and
prove that recovery preserves one Task ID, completes the link, and drains the
intent/outbox without a duplicate Task.  The frontend scenario must verify the
supplied prior frontend image’s embedded artifact SHA and use its real `/api`
calls through the gateway against the candidate backend.  This prevents a mock
old-client response from being reported as compatibility evidence.

Evidence manifests intentionally contain run ID, commit SHA, image/artifact
digests, generated resource names, scenario outcomes, and a hash of redacted
credentials.  They never include credentials, tenant paths, state contents,
or a repository-relative output path.
