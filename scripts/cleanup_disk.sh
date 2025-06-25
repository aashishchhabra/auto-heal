#!/bin/bash
# Script to clean up disk space
set -e
echo "Cleaning up disk space..."
sudo rm -rf /tmp/*
sudo apt-get clean || true
echo "Disk cleanup complete."
