#!/bin/sh
# Creates the KnowledgeOS buckets and a 7-day expiry rule on the quarantine bucket.
# Idempotent: safe to run on every `make up` (`mc ilm import` replaces the whole lifecycle config).
set -eu

for bucket in $BUCKETS; do
  mc mb --ignore-existing "local/$bucket"
  mc anonymous set none "local/$bucket"
done

echo '{"Rules":[{"ID":"expire-quarantine-7d","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":7}}]}' \
  | mc ilm import "local/$QUARANTINE"

echo "minio-init: buckets ready: $BUCKETS"
