#!/usr/bin/env bash
# One-command deploy: creates a public GitHub repo, pushes, turns on GitHub
# Pages, and kicks off the first sweep. Requires the GitHub CLI (`gh`).
#
#   ./deploy.sh              # repo named "first-pitch"
#   ./deploy.sh my-repo-name # custom repo name
set -euo pipefail

REPO_NAME="${1:-first-pitch}"
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

command -v gh >/dev/null 2>&1 || {
  echo "The GitHub CLI is required. Install it with:  brew install gh"
  exit 1
}

gh auth status >/dev/null 2>&1 || {
  say "You need to log in to GitHub first (a browser window will open)."
  gh auth login
}

USER=$(gh api user -q .login)

say "1/4  Committing the site…"
git add -A
git commit -q -m "deploy: first pitch" 2>/dev/null || true

say "2/4  Creating github.com/$USER/$REPO_NAME and pushing…"
if gh repo view "$USER/$REPO_NAME" >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$USER/$REPO_NAME.git"
  git push -u origin main
else
  git branch -M main
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push \
    --description "College softball coaching jobs, swept every 6 hours"
fi

say "3/4  Turning on GitHub Pages…"
gh api -X POST "repos/$USER/$REPO_NAME/pages" \
  -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 || \
gh api -X PUT "repos/$USER/$REPO_NAME/pages" \
  -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 || true

say "4/4  Running the first sweep in the cloud…"
sleep 2
gh workflow run sweep.yml -R "$USER/$REPO_NAME" >/dev/null 2>&1 || true

URL="https://$USER.github.io/$REPO_NAME/"
say "Done! The site will be live in ~2 minutes at:"
echo "    $URL"
echo
echo "It re-sweeps every job board automatically every 6 hours."
echo "Send that link to your coach — that's all she needs."
