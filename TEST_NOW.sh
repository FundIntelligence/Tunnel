#!/bin/bash

# 🚀 FundIQ - Quick Test Script
# This script sets up and tests the complete frontend-backend flow

echo "🚀 =================================================="
echo "   FundIQ Frontend-Backend Integration Test"
echo "=================================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Step 1: Create .env.local
echo -e "${BLUE}Step 1: Creating .env.local...${NC}"
cat > .env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
EOF

if [ -f ".env.local" ]; then
    echo -e "${GREEN}✅ .env.local created successfully${NC}"
else
    echo "❌ Failed to create .env.local"
    exit 1
fi

echo ""

# Step 2: Check if backend is running
echo -e "${BLUE}Step 2: Checking if backend is running...${NC}"
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo -e "${GREEN}✅ Backend is already running on port 8000${NC}"
    echo "   (If you want to restart it, run: lsof -ti:8000 | xargs kill -9)"
else
    echo "⚠️  Backend not running. Starting it now..."
    cd backend
    source venv/bin/activate
    python main.py > ../backend.log 2>&1 &
    BACKEND_PID=$!
    sleep 2
    cd ..
    echo -e "${GREEN}✅ Backend started (PID: $BACKEND_PID, logs: backend.log)${NC}"
fi

echo ""

# Step 3: Test health check
echo -e "${BLUE}Step 3: Testing backend health...${NC}"
HEALTH=$(curl -s http://localhost:8000/health)
if [[ $HEALTH == *"healthy"* ]]; then
    echo -e "${GREEN}✅ Backend is healthy${NC}"
    echo "   Response: $HEALTH"
else
    echo "❌ Backend health check failed"
    echo "   Response: $HEALTH"
fi

echo ""

# Step 4: Check frontend dependencies
echo -e "${BLUE}Step 4: Checking frontend setup...${NC}"
if [ -d "node_modules" ]; then
    echo -e "${GREEN}✅ Node modules installed${NC}"
else
    echo "⚠️  Installing node modules..."
    npm install
fi

echo ""

# Step 5: Start frontend
echo -e "${BLUE}Step 5: Starting frontend...${NC}"
if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null ; then
    echo -e "${GREEN}✅ Frontend is already running on port 3000${NC}"
else
    npm run dev > frontend.log 2>&1 &
    FRONTEND_PID=$!
    sleep 3
    echo -e "${GREEN}✅ Frontend started (PID: $FRONTEND_PID, logs: frontend.log)${NC}"
fi

echo ""

# Summary
echo "=================================================="
echo "✅ SETUP COMPLETE!"
echo "=================================================="
echo ""
echo "🌐 URLs:"
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8000"
echo "   Health:   http://localhost:8000/health"
echo ""
echo "📝 Next Steps:"
echo "   1. Open http://localhost:3000 in your browser"
echo "   2. Upload a test file (PDF, CSV, or XLSX)"
echo "   3. Watch backend logs: tail -f backend.log"
echo ""
echo "📊 Backend Logs:"
echo "   • Check for: [DEBUG] Using Supabase Service Role Key"
echo "   • Watch for upload progress and completion messages"
echo "   • Verify NO RLS errors appear"
echo ""
echo "🐛 Troubleshooting:"
echo "   • Backend logs: tail -f backend.log"
echo "   • Frontend logs: tail -f frontend.log"
echo "   • Kill backend: lsof -ti:8000 | xargs kill -9"
echo "   • Kill frontend: lsof -ti:3000 | xargs kill -9"
echo ""
echo "📚 Documentation: See FRONTEND_BACKEND_TESTING.md"
echo "=================================================="
echo ""

# Open browser (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "🌐 Opening browser..."
    sleep 1
    open http://localhost:3000
fi

echo ""
echo "🎉 Ready to test! Upload a file and watch the magic happen! ✨"
echo ""




