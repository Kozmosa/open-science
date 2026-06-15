# Git Workflow & Worktree Hygiene

Branching strategy, worktree conventions, and PR content expectations.
Read this when creating branches, managing worktrees, performing repository
hygiene audits, or preparing pull requests.

Commit message conventions remain in AGENTS.md (Commit & Pull Request Guidelines).
Long-lived engineering constraints are in [PROJECT_BASIS.md](../PROJECT_BASIS.md).

## Git Workflow

- `master` is the protected stable branch. Treat it as read-mostly: sync from it, review from it, and merge into it via PR only.
- `develop` is the pre-release integration buffer. It may accept direct merges for validation/integration, but it is not the default branch to start feature work from.
- Start every new feature, fix, refactor, docs, or chore branch from the latest `master`, not from `develop`.
- Preferred branch prefixes are: `feat/`, `fix/`, `refactor/`, `docs/`, and `chore/`.
- Agent-only temporary branches should not be pushed to the remote and should be deleted after their useful changes are merged or extracted.

## Worktree Hygiene

- Default to worktree-first development for non-trivial work.
- The main workspace should stay clean and should not be the default place for feature implementation.
- Use `/.worktrees/<branch>` for formal development worktrees.
- Treat `/.claude/worktrees/` as temporary agent execution space only, not as a long-lived development location.
- After a branch is merged or abandoned, remove its corresponding worktree and delete the local branch.
- Regularly prune stale remote-tracking refs with `git fetch --prune origin` when reviewing repository hygiene.
- When auditing hygiene, inspect `git worktree list --porcelain` and `git branch -vv` before deleting anything.
- Preserve dirty or unaudited worktrees until their state is understood.

> **For day-to-day worktree mechanics (CWD, npm --prefix, tsc, sed pitfalls)**: [worktree-working-guide.md](worktree-working-guide.md)

## Pull Request Content

Pull requests should include:

- a brief summary of what changed,
- the commands you ran to validate it,
- screenshots only for docs/site rendering changes,
- links to related issues or design notes when applicable.
