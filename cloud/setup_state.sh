#!/usr/bin/env bash
# Clones the bot-state branch into state/ (or starts it), then writes the env files from secrets.
# Used by every cloud workflow. Run from the workspace root with REPO_URL, the secrets and BOT2_STATE set.
set -euo pipefail
if git ls-remote --exit-code --heads "$REPO_URL" bot-state >/dev/null; then
  git clone -q --branch bot-state "$REPO_URL" state
else
  mkdir state && (cd state && git init -q -b bot-state && git remote add origin "$REPO_URL")
fi
cp code/cloud/gitignore state/.gitignore
cp code/cloud/fleet.json state/fleet.json
if [ "${BOT1_CLOUD:-}" = on ]; then  # bot 1 moved here: Medic and Guard look after it on this side
  python3 -c 'import json; p="state/fleet.json"; f=json.load(open(p)); f["1"]={"runs_on": "cloud"}; json.dump(f, open(p, "w"), indent=1)'
fi
if [ ! -f state/rotation_state.json ] && [ -n "${BOT2_STATE:-}" ]; then echo "$BOT2_STATE" > state/rotation_state.json; fi
cd state
umask 077
[ -n "${BOT1_ENV:-}" ] && printf '%s\n' "$BOT1_ENV" > .env
printf 'ALPACA_API_KEY=%s\nALPACA_SECRET_KEY=%s\n' "${BOT2_KEY:-}" "${BOT2_SECRET:-}" > .env.rotation
printf 'ALPACA_API_KEY=%s\nALPACA_SECRET_KEY=%s\n' "${BOT3_KEY:-}" "${BOT3_SECRET:-}" > .env.crypto
git config user.name "cloud-bots"
git config user.email "cloud-bots@users.noreply.github.com"
