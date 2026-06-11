#!/usr/bin/env bash
# Runs a command with the EC2 instance role's temporary credentials exported
# as environment variables. Needed for tools (e.g. Remotion Lambda) that
# require explicit AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN env vars instead
# of using the default instance-role credential chain.
#
# Usage: deployment/run-with-instance-creds.sh npx remotion lambda ...
set -euo pipefail

T=$(curl -s -X PUT -H "X-aws-ec2-metadata-token-ttl-seconds: 900" \
    http://169.254.169.254/latest/api/token)
ROLE=$(curl -s -H "X-aws-ec2-metadata-token: $T" \
    http://169.254.169.254/latest/meta-data/iam/security-credentials/)
CREDS=$(curl -s -H "X-aws-ec2-metadata-token: $T" \
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/$ROLE")

AWS_ACCESS_KEY_ID=$(python3 -c 'import sys,json;print(json.loads(sys.argv[1])["AccessKeyId"])' "$CREDS")
AWS_SECRET_ACCESS_KEY=$(python3 -c 'import sys,json;print(json.loads(sys.argv[1])["SecretAccessKey"])' "$CREDS")
AWS_SESSION_TOKEN=$(python3 -c 'import sys,json;print(json.loads(sys.argv[1])["Token"])' "$CREDS")
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN

exec "$@"
