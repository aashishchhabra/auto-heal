#!/bin/bash
# Simple health check script
echo "Performing health check..."
if uptime; then
  echo "Health check passed."
  exit 0
else
  echo "Health check failed."
  exit 1
fi
