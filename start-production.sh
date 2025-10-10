#!/bin/bash

echo "🚀 Starting FundIQ Production (Supabase Backend)"
echo "================================================"

# Check if we're in the right directory
if [ ! -f "package.json" ]; then
    echo "❌ Please run this from the Tunnel directory"
    exit 1
fi

# Check if environment variables are set
if [ ! -f ".env.local" ]; then
    echo "❌ Missing .env.local file. Please create it with your Supabase credentials."
    exit 1
fi

# Start the main backend (Supabase)
echo "🔧 Starting Production Backend (Supabase)..."
cd backend
source venv/bin/activate
uvicorn main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# Wait a moment for backend to start
sleep 3

# Check if backend is running
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✅ Backend started successfully"
else
    echo "❌ Backend failed to start"
    exit 1
fi

# Go back to main directory
cd ..

echo "🌐 Starting Frontend..."
echo "📱 Production app: http://localhost:3000"
echo "📱 Simple demo: http://localhost:3001/simple-page"
echo ""
echo "🎯 To test:"
echo "   1. Open http://localhost:3000 (main app with Supabase)"
echo "   2. Or http://localhost:3001/simple-page (simple demo)"
echo "   3. Upload PDF, CSV, or XLSX files"
echo "   4. View extracted data and download results"
echo ""
echo "⚠️  Note: For main app to work, run the RLS fix SQL in Supabase dashboard"
echo "Press Ctrl+C to stop both servers"

# Start frontend
npm run dev

# Cleanup function
cleanup() {
    echo ""
    echo "🛑 Stopping servers..."
    kill $BACKEND_PID 2>/dev/null
    exit 0
}

# Set up signal handling
trap cleanup SIGINT SIGTERM

# Wait for background process
wait $BACKEND_PID
