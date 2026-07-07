#!/bin/bash
# Starts the dashboard server and opens Chromium in kiosk mode
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

# Kill previous chromium instances to avoid "existing session" issue
pkill -15 chromium 2>/dev/null
sleep 1

# Start Flask dashboard in background
python3 dashboard_server.py &
DASH_PID=$!

# Wait for server to be ready
for i in $(seq 1 15); do
  if curl -s http://localhost:5100 > /dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# Launch Chromium kiosk (fresh profile to avoid session reuse)
KIOSK_DIR="/tmp/chromium-kiosk-$(date +%s)"
chromium --kiosk --no-sandbox --disable-infobars --disable-session-crashed-bubble \
  --disable-features=TranslateUI --noerrdialogs \
  --user-data-dir="$KIOSK_DIR" \
  http://localhost:5100 &

CHROMIUM_PID=$!

# Keep running while both processes are alive
while kill -0 $DASH_PID 2>/dev/null; do
  if ! kill -0 $CHROMIUM_PID 2>/dev/null; then
    # Chromium died; restart it
    chromium --kiosk --no-sandbox --disable-infobars --disable-session-crashed-bubble \
      --disable-features=TranslateUI --noerrdialogs \
      --user-data-dir="/tmp/chromium-kiosk-$(date +%s)" \
      http://localhost:5100 &
    CHROMIUM_PID=$!
  fi
  sleep 5
done

kill $CHROMIUM_PID 2>/dev/null
wait
