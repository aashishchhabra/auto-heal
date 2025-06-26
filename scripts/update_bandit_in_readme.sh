#!/bin/zsh
# Update Bandit security scan result in README.md (for pre-commit)

bandit -r src/ -ll > bandit_result.txt
BANDIT_ISSUES=$(grep -Eo 'No issues identified.' bandit_result.txt || grep -Eo 'Files scanned.*' bandit_result.txt)
SCAN_DATE=$(date +'%Y-%m-%d')
if [[ -z "$BANDIT_ISSUES" ]]; then
  BANDIT_ISSUES="Issues found!"
fi
sed -i '' -E "s|(^- \*\*Security Scan:\*\* ).*|\1Bandit ($BANDIT_ISSUES, last scan: $SCAN_DATE)|" README.md
rm bandit_result.txt
