#!/usr/bin/env bash
# Deregisters every demo AMI except the newest, and deletes their snapshots.
# Run only after a successful bake, so a failed build never leaves zero AMIs to launch from.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
KEEP="${KEEP_AMIS:-1}"

STALE_AMIS=$(
  aws ec2 describe-images --region "$REGION" --owners self \
    --filters "Name=tag:Role,Values=demo-ami" "Name=state,Values=available" \
    --query "reverse(sort_by(Images, &CreationDate))[${KEEP}:].ImageId" --output text
)

if [ -z "$STALE_AMIS" ]; then
  echo "nothing to prune: ${KEEP} or fewer demo AMIs exist"
  exit 0
fi

for ami in $STALE_AMIS; do
  snapshots=$(aws ec2 describe-images --region "$REGION" --image-ids "$ami" \
    --query "Images[0].BlockDeviceMappings[].Ebs.SnapshotId" --output text)
  aws ec2 deregister-image --region "$REGION" --image-id "$ami" >/dev/null
  for snapshot in $snapshots; do
    aws ec2 delete-snapshot --region "$REGION" --snapshot-id "$snapshot"
  done
  echo "pruned ${ami} (snapshots: ${snapshots})"
done
