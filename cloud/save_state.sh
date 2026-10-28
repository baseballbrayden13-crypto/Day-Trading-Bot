#!/usr/bin/env bash
# Commits state/ to the bot-state branch. Several jobs save to it at once (and bots keep running
# while they do), so this never touches the files a running bot has open: this job's changes are
# committed locally, and if the push is rejected they are replayed onto a fresh clone of the branch
# (this job's version wins a clash) and pushed from there.
# Usage (from state/): save_state.sh "what ran"
set -uo pipefail
msg="$1"
git rev-parse -q --verify HEAD > .git/pushed 2>/dev/null || : > .git/pushed   # where this clone started
git add -A
git commit -qm "Cloud run $msg $(date -u +%FT%TZ)" || true
head=$(git rev-parse -q --verify HEAD) || exit 0
pushed=$(cat .git/pushed)
[ "$head" = "$pushed" ] && exit 0
git push -q origin HEAD:bot-state 2>/dev/null && { echo "$head" > .git/pushed; exit 0; }
[ -n "$pushed" ] || { echo "First push of bot-state was rejected" >&2; exit 1; }
url=$(git remote get-url origin)
tmp=$(mktemp -d)
for i in 1 2 3 4 5; do
  rm -rf "$tmp/c"
  git clone -q --branch bot-state --single-branch "$url" "$tmp/c" || { sleep $((i * 3)); continue; }
  # everything this job changed since it last pushed, as one commit on top of what it started from
  git update-ref refs/tmp/replay "$(git commit-tree "$head^{tree}" -p "$pushed" -m "Cloud run $msg $(date -u +%FT%TZ)")"
  git -C "$tmp/c" fetch -q "$PWD" refs/tmp/replay
  git -C "$tmp/c" -c user.name=cloud-bots -c user.email=cloud-bots@users.noreply.github.com \
    cherry-pick -X theirs --allow-empty --keep-redundant-commits FETCH_HEAD >/dev/null 2>&1 \
    || { git -C "$tmp/c" cherry-pick --abort 2>/dev/null; sleep $((i * 3)); continue; }
  if git -C "$tmp/c" push -q origin HEAD:bot-state 2>/dev/null; then echo "$head" > .git/pushed; exit 0; fi
  sleep $((i * 3))
done
echo "Could not save state after 5 tries" >&2
exit 1
