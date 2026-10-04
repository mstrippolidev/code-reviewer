#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

REGION="${AWS_REGION:-us-east-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
DESTINATION="s3://code-reviewer-tfstate-${ACCOUNT_ID}/runtime/api.env"
KEYS=(
  API_JWT_SECRET_KEY
  API_TOKEN_ENCRYPTION_KEY
  GITHUB_OAUTH_CLIENT_ID
  GITHUB_OAUTH_CLIENT_SECRET
  OPENROUTER_API_KEY
  GUARDRAILS_API_KEY
)

env_file=$(mktemp)
trap 'rm -f "$env_file"' EXIT

for key in "${KEYS[@]}"; do
  value=$(grep -E "^${key}=" .env | head -1 | cut -d= -f2- | sed -E "s/^['\"]|['\"]$//g")
  if [ -z "$value" ]; then
    echo "${key} is missing or empty in .env" >&2
    exit 1
  fi
  echo "${key}=${value}" >> "$env_file"
done

aws s3 cp --region "$REGION" --sse AES256 "$env_file" "$DESTINATION"
echo "uploaded ${#KEYS[@]} keys to ${DESTINATION}"
