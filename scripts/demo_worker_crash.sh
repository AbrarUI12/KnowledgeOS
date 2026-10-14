#!/usr/bin/env bash
# Demo 12 (S20): kill an ingestion worker mid-stage and watch the job recover.
#
# Restarts the worker with slow stages (3 s each) and short leases (15 s) so there's time to kill
# it mid-run, plus beat with a fast reconciler (every 10 s, stale after 30 s). The worker runs the
# full pipeline: until every real parsing/chunking library has merged, parsing → chunking use the
# T1.0 contract fakes (infra/docker/compose.crash-test.yml), so chunks really persist. Then it
# runs tests/test_worker_crash.py against the local stack:
#   clean run → crash run (docker kill + start mid-stage) → reconciler re-queues the stranded job
#   once the dead worker's lease expires → it resumes from its checkpoint → same (positive) chunk
#   count.
#
# The shared worker and beat are always restored to normal settings on exit, even when the test
# fails or the demo is interrupted (Ctrl+C); the exit status is the test's.
#
# Prerequisites: `make up` (core stack) and `make migrate`.
set -euo pipefail
cd "$(dirname "$0")/.."

restore() {
  local status=$?
  trap - EXIT INT TERM
  unset INGESTION_DEBUG_STAGE_DELAY_SECONDS INGESTION_LEASE_SECONDS RECONCILE_INTERVAL_SECONDS RECONCILE_STALE_SECONDS
  # Recreates the worker without the fakes mount and beat with the normal reconciler cadence.
  docker compose --profile full up -d worker beat || echo "restore failed: run 'docker compose --profile full up -d worker beat'" >&2
  exit "$status"
}
trap restore EXIT
trap 'exit 130' INT TERM

export MALWARE_SCANNER="${MALWARE_SCANNER:-none}"   # the core profile has no ClamAV container
export INGESTION_DEBUG_STAGE_DELAY_SECONDS=3
export INGESTION_LEASE_SECONDS=15
export RECONCILE_INTERVAL_SECONDS=10
export RECONCILE_STALE_SECONDS=30

docker compose -f docker-compose.yml -f infra/docker/compose.crash-test.yml --profile full \
  up -d --build worker dispatcher beat
KOS_CRASH_TEST=1 uv --directory apps/api run pytest -m crash tests/test_worker_crash.py -v -s
