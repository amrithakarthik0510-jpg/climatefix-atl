#!/bin/bash
# Double-click this to start ClimateFix ATL.
# It frees port 8000, starts the report-saving server, and opens the app.
cd "$(dirname "$0")"
echo "Starting ClimateFix ATL..."
echo

# Free port 8000 if a previous server is stuck (this is what was breaking it)
STUCK=$(lsof -ti tcp:8000 2>/dev/null)
if [ -n "$STUCK" ]; then
  echo "Clearing a previous server still on port 8000..."
  echo "$STUCK" | xargs kill -9 2>/dev/null
  sleep 1
fi

echo "Leave this window open. Press Ctrl+C here when you're done."
echo
# open the app once the server is up
( sleep 2; open "http://localhost:8000/frontend/index.html" ) &
python3 scripts/server.py || python scripts/server.py
