#!/usr/bin/env bash
set -euo pipefail

source /etc/code-reviewer/boot.env

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
export PATH="$PATH:/usr/local/bin"

APP_DIR=/opt/code-reviewer
NAMESPACE=code-reviewer

imds() {
  local token
  token=$(curl -sX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  curl -s -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$1"
}

retry() {
  local attempts=$1
  shift
  for _ in $(seq 1 "$attempts"); do
    "$@" && return 0
    sleep 10
  done
  return 1
}

retry 18 kubectl wait --for=condition=Ready node --all --timeout=5s

for operator in strimzi cnpg; do
  kubectl apply --server-side -f "$APP_DIR/operators/$operator.yaml"
done

kubectl wait --for=condition=Established --timeout=120s \
  crd/kafkas.kafka.strimzi.io crd/clusters.postgresql.cnpg.io
kubectl -n kafka rollout status deploy/strimzi-cluster-operator --timeout=180s
kubectl -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=180s

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

region=$(imds placement/region)
account_id=$(aws sts get-caller-identity --query Account --output text)
env_file=$(mktemp)
trap 'rm -f "$env_file"' EXIT
aws s3 cp --region "$region" "s3://code-reviewer-tfstate-${account_id}/runtime/api.env" "$env_file"
kubectl -n "$NAMESPACE" create secret generic api-secrets \
  --from-env-file="$env_file" --dry-run=client -o yaml | kubectl apply -f -

render_overlay() {
  kubectl kustomize "$APP_DIR/k8s/overlays/single-node" | sed "s#<ECR_REGISTRY>#${ECR_REGISTRY}#g"
}

# CNPG's admission webhook can lag its rollout status, so the first apply may be refused.
retry 5 bash -c "$(declare -f render_overlay); APP_DIR=$APP_DIR ECR_REGISTRY=$ECR_REGISTRY KUBECONFIG=$KUBECONFIG render_overlay | kubectl apply --server-side -f -"
