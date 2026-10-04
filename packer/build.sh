#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REGION="${AWS_REGION:-us-east-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

tar -czf k8s.tar.gz -C ../k8s .

packer init .
packer build \
  -var "region=${REGION}" \
  -var "ecr_registry=${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com" \
  -var "ecr_password=$(aws ecr get-login-password --region "$REGION")" \
  .
