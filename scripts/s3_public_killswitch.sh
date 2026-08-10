#!/usr/bin/env bash
# Take the public bucket private, immediately.
#
# WHY THIS EXISTS
# ---------------
# `airlock-redaction` is world-readable and holds ~16 GB. AWS gives 100 GB/month
# of free egress and then charges $0.09/GB, with no spending limit and no hard
# cap available anywhere in S3. A crawler, a mirror, or one popular link can
# therefore run up an unbounded bill, and the budget alarm is a notification --
# it does not stop anything.
#
# So the guard is: an alarm tells you, and this script is what you run. Keep the
# two together; an alarm with no rehearsed response is just a nastier way to
# find out.
#
#   scripts/s3_public_killswitch.sh off     # revoke public access now
#   scripts/s3_public_killswitch.sh on      # restore public read-only
#   scripts/s3_public_killswitch.sh status  # what is it right now
#
# Nothing is deleted either way -- this only flips the bucket policy.
set -euo pipefail

BUCKET="${AIRLOCK_PUBLIC_BUCKET:-airlock-redaction}"
PROFILE="${AWS_PROFILE:-default}"

policy_json() {
  cat <<JSON
{
  "Version": "2012-10-17",
  "Id": "AirlockPublicReadOnly",
  "Statement": [
    {
      "Sid": "PublicReadObjects",
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::${BUCKET}",
        "arn:aws:s3:::${BUCKET}/*"
      ]
    }
  ]
}
JSON
}

case "${1:-status}" in
  off)
    aws s3api delete-bucket-policy --bucket "$BUCKET" --profile "$PROFILE"
    # Re-arm the account-level block so a stray policy cannot reopen it.
    aws s3api put-public-access-block --bucket "$BUCKET" --profile "$PROFILE" \
      --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    echo "PRIVATE — public policy removed and public access re-blocked."
    ;;
  on)
    aws s3api put-public-access-block --bucket "$BUCKET" --profile "$PROFILE" \
      --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false
    policy_json | aws s3api put-bucket-policy --bucket "$BUCKET" --profile "$PROFILE" --policy file:///dev/stdin
    echo "PUBLIC — read-only policy applied."
    ;;
  status)
    code=$(curl -s -o /dev/null -w '%{http_code}' \
      "https://${BUCKET}.s3.amazonaws.com/?list-type=2&max-keys=1")
    case "$code" in
      200) echo "PUBLIC  (anonymous list returned 200)";;
      403) echo "PRIVATE (anonymous list returned 403)";;
      *)   echo "unexpected HTTP $code";;
    esac
    # Month-to-date S3 spend, so the number and the switch live in one place.
    acct=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
    aws budgets describe-budget --account-id "$acct" --budget-name airlock-s3-guard \
      --profile "$PROFILE" \
      --query 'Budget.{limit:BudgetLimit.Amount,spent:CalculatedSpend.ActualSpend.Amount}' 2>/dev/null \
      || echo "  (budget airlock-s3-guard not found)"
    ;;
  *)
    echo "usage: $0 {on|off|status}" >&2; exit 2;;
esac
