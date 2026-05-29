#!/usr/bin/env bash
# Deploy only docs/ainrf/ to GitHub Pages (gh-pages branch)
# Usage: ./scripts/deploy-ainrf-docs.sh

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "=== Deploy AINRF docs to GitHub Pages ==="

# Check if mkdocs is available
if command -v mkdocs &>/dev/null; then
    echo "MkDocs found. Using mkdocs gh-deploy..."
    pip install -q mkdocs-material pymdown-extensions mkdocs-mermaid2-plugin mkdocs-roamlinks-plugin 2>/dev/null || true
    mkdocs gh-deploy -f mkdocs-ainrf.yml --message "Deploy ainrf docs from $(git rev-parse --short HEAD)"
    echo "Done! Deployed via mkdocs gh-deploy."
    exit 0
fi

# Fallback: deploy from pre-built site/ainrf/ directory
echo "MkDocs not found. Falling back to manual deploy from site/ainrf/..."

if [[ ! -d site/ainrf ]]; then
    echo "Error: site/ainrf/ not found. Please build docs first or install mkdocs."
    exit 1
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Copy ainrf content and assets
mkdir -p "$TMPDIR"
cp -r site/ainrf/* "$TMPDIR/"

# Assets are referenced as ../assets/ from site/ainrf/ pages.
# Copy them to the root of the deploy so paths work.
if [[ -d site/assets ]]; then
    cp -r site/assets "$TMPDIR/"
fi

# Fix relative paths in HTML: ../assets/ → ./assets/
find "$TMPDIR" -name '*.html' -exec sed -i 's|"\.\./assets/|"./assets/|g' {} +

# Fix breadcrumb/home links: href=".." → href="."
# Be careful to only match exact ".." (not "../foo")
find "$TMPDIR" -name '*.html' -exec sed -i 's|href="\.\."|href="."|g' {} +

COMMIT=$(git rev-parse --short HEAD)
ORIGIN_URL=$(git remote get-url origin)

cd "$TMPDIR"
git init --quiet
git checkout -b gh-pages
git add .
git commit -m "Deploy ainrf docs from ${COMMIT}" --quiet
git remote add origin "$ORIGIN_URL"
echo "Pushing to origin/gh-pages ..."
git push -f origin gh-pages

echo "Done! AINRF docs deployed to gh-pages branch."
echo "Next: enable GitHub Pages in repo settings → Pages → Source = Deploy from a branch → gh-pages → / (root)"
