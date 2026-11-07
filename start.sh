#!/bin/sh
cd "$(dirname "$0")"
echo "Astra is running at http://localhost:8000  (Ctrl+C to stop)"
( sleep 1; (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || (command -v open >/dev/null && open http://localhost:8000) ) >/dev/null 2>&1 &
exec python3 -m http.server 8000
