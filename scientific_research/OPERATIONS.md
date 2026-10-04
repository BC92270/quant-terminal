# Scientific Research Brain v0.6.8.0 — live operations runbook

This runbook operates the Codespace deployment without changing scientific meaning. Runtime state is external to Git, every network acquisition remains explicit, and every release remains `RESEARCH_ONLY`.

## Canonical live layout

```text
/workspaces/quant-terminal-srb-v0680-live   immutable release checkout
/workspaces/quant-terminal/.scientific_research_data   governed runtime state
/workspaces/.codex-runtime-srb-v0680       PID, log, local backups and acceptance evidence
```

The release checkout must resolve to the published annotated v0.6.8.0 tag. The state root may be reused from v0.6.7.0 because Phase 6.8 is additive: it adds `phase68_prospective_observation_programs.json` only after an explicit freeze and does not rewrite earlier registries on view.

The runtime directory and the state root are on the same Codespace storage. A copy under `/workspaces` is a local rollback copy, not an independent long-term backup.

## Release and dependency preflight

Run from the release checkout before starting Streamlit:

```bash
bash <<'SRB_PREFLIGHT'
set -euo pipefail
cd /workspaces/quant-terminal-srb-v0680-live
release_tag="scientific-research-v0.6.8.0"
test "$(git cat-file -t "$release_tag")" = "tag"
expected_commit="$(git rev-list -n 1 "$release_tag")"
actual_commit="$(git rev-parse HEAD)"
test "$actual_commit" = "$expected_commit"
test -z "$(git status --porcelain)"

python3 -m pip install -r requirements.txt
corepack enable
corepack prepare pnpm@11.25.0 --activate
pnpm --dir scientific_research install --frozen-lockfile
SRB_PREFLIGHT
```

The Python and Node suites in `VERIFICATION.md` must pass in this exact checkout. Dependency success in another worktree is not release evidence.

## Pre-release backup and independent retention

Stop every process that can write the state root and confirm port 8501 is closed before copying state. The commands below also acquire the same advisory lock used by the registries, generate a complete SHA-256 inventory and verify the local copy.

```bash
bash <<'SRB_BACKUP'
set -euo pipefail
state_root="/workspaces/quant-terminal/.scientific_research_data"
runtime_root="/workspaces/.codex-runtime-srb-v0680"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_root="$runtime_root/backups/$stamp"

test -d "$state_root"
if ss -ltnH 'sport = :8501' | grep -q .; then
  echo "Port 8501 is still occupied; stop the exact writer before taking the release backup" >&2
  exit 1
fi
test ! -e "$backup_root"
mkdir -p "$backup_root"
exec 9>"$state_root/.srb-registry.lock"
flock -w 10 -x 9 || { echo "Could not acquire the registry lock" >&2; exit 1; }
cp -a "$state_root" "$backup_root/state"
flock -u 9
exec 9>&-

(
  cd "$backup_root"
  find state -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
find "$backup_root/state" -type f | wc -l
du -sb "$backup_root/state"
printf '%s\n' "$backup_root" > "$runtime_root/latest-verified-backup.txt"
SRB_BACKUP
```

For the 300-day prospective program, copy the verified backup to storage mounted from outside the Codespace. The destination must not resolve below `/workspaces`:

```bash
bash <<'SRB_EXTERNAL_COPY'
set -euo pipefail
runtime_root="/workspaces/.codex-runtime-srb-v0680"
backup_root="$(cat "$runtime_root/latest-verified-backup.txt")"
test -d "$backup_root/state"
stamp="$(basename "$backup_root")"
external_archive_root="${SRB_EXTERNAL_ARCHIVE_ROOT:?Set SRB_EXTERNAL_ARCHIVE_ROOT to a mounted off-Codespace archive}"
external_archive_root="$(readlink -m "$external_archive_root")"
case "$external_archive_root" in
  /workspaces|/workspaces/*) echo "External archive must not be on Codespace storage" >&2; exit 1 ;;
esac
mkdir -p "$external_archive_root/srb-v0680/$stamp"
external_copy="$(readlink -f "$external_archive_root/srb-v0680/$stamp")"
case "$external_copy" in
  /workspaces|/workspaces/*) echo "Resolved archive is still inside the Codespace" >&2; exit 1 ;;
esac
cp -a "$backup_root/." "$external_copy/"
(
  cd "$external_copy"
  sha256sum -c SHA256SUMS
)
SRB_EXTERNAL_COPY
```

If no externally mounted archive is available, upload the backup and `SHA256SUMS` to a governed external store, then verify the copied checksums there. Do not call the longitudinal program operationally durable while its only copies remain in one Codespace. Respect source terms and access controls when choosing the external store.

## Start, PID binding and health

Complete the release preflight and backup first. Refuse to start if anything already listens on the release port; a healthy response from an older process is not acceptance evidence.

```bash
bash <<'SRB_START'
set -euo pipefail
cd /workspaces/quant-terminal-srb-v0680-live
runtime_root="/workspaces/.codex-runtime-srb-v0680"
export SRB_MEMORY_DIR="/workspaces/quant-terminal/.scientific_research_data"
mkdir -p "$runtime_root"

if ss -ltnH 'sport = :8501' | grep -q .; then
  echo "Port 8501 is already occupied; inspect and stop the exact owner before deployment" >&2
  exit 1
fi

pid_file="$runtime_root/streamlit.pid"
rm -f "$pid_file"
nohup setsid -f sh -c '
  set -eu
  printf "%s\n" "$$" > "$1"
  exec python3 -m streamlit run app.py \
    --server.address 0.0.0.0 \
    --server.port 8501 \
    --server.headless true
' sh "$pid_file" > "$runtime_root/streamlit.log" 2>&1 < /dev/null &

for attempt in $(seq 1 20); do
  test -s "$pid_file" && break
  sleep 1
done
test -s "$pid_file"
runtime_pid="$(cat "$pid_file")"
case "$runtime_pid" in
  ''|*[!0-9]*) echo "Invalid Streamlit PID" >&2; exit 1 ;;
esac
kill -0 "$runtime_pid"

health_ready="false"
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8501/_stcore/health > "$runtime_root/health.txt"; then
    health_ready="true"
    break
  fi
  if ! kill -0 "$runtime_pid" 2>/dev/null; then
    tail -n 120 "$runtime_root/streamlit.log"
    exit 1
  fi
  sleep 1
done
test "$health_ready" = "true"
grep -Fx "ok" "$runtime_root/health.txt"

test "$(readlink -f "/proc/$runtime_pid/cwd")" = "/workspaces/quant-terminal-srb-v0680-live"
tr '\0' '\n' < "/proc/$runtime_pid/environ" | grep -Fx "SRB_MEMORY_DIR=$SRB_MEMORY_DIR"
ps -o pid,ppid,sid,lstart,command -p "$runtime_pid"
ps -p "$runtime_pid" -o args= | grep -F -- "streamlit run app.py"
test "$(git rev-parse HEAD)" = "$(git rev-list -n 1 scientific-research-v0.6.8.0)"
tail -n 120 "$runtime_root/streamlit.log"
SRB_START
```

A valid health response is necessary but not sufficient. Acceptance also requires the PID checks above, exact commit/tag, route rendering, selected state root, current log tail and browser console.

## One-time v0.6.7.0 → v0.6.8.0 state activation

The code migration is additive, but the new gate changes the combined operational Mission state until its operating contract is explicitly frozen. On an otherwise complete v0.6.7.0 state root, the first v0.6.8.0 render is expected to show `PROSPECTIVE_OBSERVATION_PROTOCOL = NOT_EVALUATED`, 21/22 satisfied gates and operational `WAITING_EVIDENCE`, while `core_study_status` remains `READY_FOR_REVIEW`. This temporary state does not invalidate or rewrite the retained study result.

After the pre-release backup, dependency/test verification and exact-release start:

1. Open `?workspace=scientific-research` and verify that every pre-existing artifact identity is unchanged.
2. In `Validation & Learning → Independent Replication → Prospective Evidence Clock`, inspect the latest eligible completed direct-BIS seed.
3. Expand the immutable preregistration, compare the seed reconciliation/snapshot/raw/reconciliation hashes, tick the explicit irreversible-freeze confirmation, then click **Freeze prospective monthly observation program** once. This stores the cadence and performs no network request.
4. Record the program ID, seed reconciliation/snapshot IDs, protocol fingerprint and first eligible UTC window in the acceptance evidence.
5. Reopen `Command Center → Closure Cockpit`. If the prior 21 gates remain satisfied, Mission Control must now report 22/22 and `READY_FOR_REVIEW`; longitudinal maturity must remain `WARMING_UP` or its honest schedule state.
6. Restart the exact release and confirm the same program ID, gate state and artifact fingerprints rehydrate from `SRB_MEMORY_DIR`.

If a program already exists for the governed replication, do not attempt another freeze. Validate the existing program and stop on any seed, cadence, fingerprint or no-backfill conflict. Never backdate the freeze to recover an earlier month.

## Stop and restart

Resolve and validate the exact recorded PID before signaling it:

```bash
bash <<'SRB_STOP'
set -euo pipefail
runtime_root="/workspaces/.codex-runtime-srb-v0680"
runtime_pid="$(cat "$runtime_root/streamlit.pid")"
case "$runtime_pid" in
  ''|*[!0-9]*) echo "Invalid Streamlit PID" >&2; exit 1 ;;
esac
test "$(readlink -f "/proc/$runtime_pid/cwd")" = "/workspaces/quant-terminal-srb-v0680-live"
ps -o pid,ppid,sid,lstart,command -p "$runtime_pid"
kill -TERM "$runtime_pid"
for attempt in $(seq 1 30); do
  kill -0 "$runtime_pid" 2>/dev/null || break
  sleep 1
done
if kill -0 "$runtime_pid" 2>/dev/null; then
  echo "Streamlit did not stop cleanly; inspect it before taking further action" >&2
  exit 1
fi
SRB_STOP
```

Restart with the start procedure, then verify health and reopen `?workspace=scientific-research`. A restart acceptance must recover the same Mission state and artifact identities from `SRB_MEMORY_DIR`.

## Restore drill

1. Stop Streamlit and confirm port 8501 is closed.
2. Run `sha256sum -c SHA256SUMS` inside the selected local or external backup.
3. Validate that the backup contains JSON arrays/JSONL files and content-addressed source artifacts.
4. Move the current state to a timestamped quarantine path; do not delete it.
5. Copy the verified `state` directory to the configured state root.
6. Start the exact release checkout.
7. Run the registry/route tests, health check and browser acceptance.
8. Compare Mission status, gate count, program/run/replication IDs and snapshot fingerprints with the pre-restore evidence.

If any identity changes unexpectedly, stop the service and restore the quarantined state. Do not repair registry JSON by hand.

## Monthly prospective observation procedure

The Phase-6.8 program is deliberately not an unattended scheduler.

1. Open `Command Center → Closure Cockpit` and confirm whether an observation is due.
2. In `Validation & Learning → Independent Replication → Prospective Evidence Clock`, freeze the current UTC-month observation before any download.
3. Execute the explicit official BIS acquisition.
4. Confirm source-integrity and coverage `PASS`, a retained raw hash, snapshot fingerprint, retrieval time and latest period.
5. Freeze and execute the Phase-6.7 OECD/BIS triangulation for the genuinely new direct snapshot when applicable.
6. Export the updated closure dossier, create a fresh checksum inventory and retain a verified off-Codespace copy with the operational evidence.

An identical archive is retained but does not increase content-distinct maturity. More than one observation in a month does not create extra schedule or maturity credit, even if the later files are content-distinct. A retrieval whose governed reconciliation completes after its UTC month closes is retained but does not repair that month. Readiness requires the seed plus credited monthly evidence to reach 12 content-distinct observations, 12 distinct latest periods and at least 300 observed days. If the month closes without eligible acquisition, the next render marks it `MISSED_RETAINED` or `MISSED_RETAINED_LATE_COMPLETION`; operators must not backdate or edit the registry.

## Incident policy

- Malformed registry, fingerprint mismatch, conflicting program, broken content-addressed artifact or unexpected production flag: stop mutation and preserve all bytes.
- Provider timeout or schema change: retain the frozen protocol and audited failure; do not weaken the parser or threshold after seeing the response.
- Duplicate or unchanged provider content: retain the observation and accept zero maturity increment.
- Browser or chart defect: it may block product acceptance but cannot change the underlying scientific record.
- Lost state: restore only from a checksum-verified independent backup; Git tags contain code, not runtime evidence.

## Rollback

Code rollback uses a separate clean checkout of the prior immutable tag. Do not reset or rewrite the live state. Phase-6.7 code ignores the additive Phase-6.8 registry file; retain that file so returning to v0.6.8.0 restores the prospective program unchanged. After rollback, repeat dependency, test, health, route and state-rehydration checks before calling the older interface live.

## Release acceptance evidence

Retain together:

- commit SHA, annotated tag object and branch;
- clean-worktree status;
- Python/Node dependency versions, suite counts and exit codes;
- local and off-Codespace backup locations, file count, byte count and verified `SHA256SUMS`;
- one-time migration evidence, including the pre-activation gate state and frozen program identity;
- state-root registry health and Mission gate summary;
- Streamlit PID, PPID, session ID, working directory, bound state-root environment and health response;
- browser route, viewport, visible Phase-6.8 cockpit and console result;
- explicit statement that longitudinal maturity, independent-investigator review and production authorization remain unestablished.
