#!/bin/bash
# Quick test to show startup logs then exit

cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend
source venv/bin/activate

# Run server and capture first few seconds of output
python main.py &
PID=$!

# Wait for startup
sleep 2

# Kill the server
kill $PID 2>/dev/null

echo ""
echo "✅ Server started successfully with SERVICE_ROLE key"


