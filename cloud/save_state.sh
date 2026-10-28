#!/usr/bin/env bash
# Commits state/ to the bot-state branch. Several workflows save to it, so on a race it rebases
# onto the newer branch and tries again. Usage (from state/): save_state.sh "what ran"
set -uo pipefail
git add -A
git commit -qm "Cloud run $1 $(date -u +%FT%TZ)" || exit 0
for i in 1 2 3 4 5; do
  git push -q origin HEAD:bot-state && exit 0
  git fetch -q origin bot-state || { git remote set-branches origin bot-state; git fetch -q origin bot-state; }
  git rebase -q --autostash -X theirs FETCH_HEAD || git rebase --abort  # on a clash this run's version of a file wins
  sleep $((i * 3))
done
echo "Could not save state after 5 tries" >&2
exit 1
