#!/bin/bash

# delete pid file if it's over 30min
find . -name cron.pid -type f -mmin +30 -delete

# stop if pid is still there
if [ -f "cron.pid" ]; then
  exit 1
fi

trap "rm -f -- cron.pid" EXIT INT KILL TERM

echo $$ > "cron.pid"

date

echo "==> newRegs"
python3 newRegs.py

echo "==> newTrends"
python3 newTrends.py

date