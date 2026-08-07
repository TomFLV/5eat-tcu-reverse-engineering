#!/bin/bash
set -e
cd /mnt/d/5eat-work/sh2
gcc -O2 -Wall -Wextra -o sh2 sh2.c
echo "built: $(ls -la sh2 | awk '{print $5}') bytes"
