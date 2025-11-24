#!/bin/bash
# FundIQ Debug Script - Automated checks for network/parsing errors

echo "🔍 FundIQ Debug Script"
echo "======================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Step 1: Check backend availability
echo "📡 Step 1: Checking backend availability..."
HEALTH_CHECK=$(curl -s http://127.0.0.1:8000/health 2>&1)
if echo "$HEALTH_CHECK" | grep -q "healthy"; then
    echo -e "${GREEN}✅ Backend is running and healthy${NC}"
    echo "$HEALTH_CHECK" | python3 -m json.tool 2>/dev/null || echo "$HEALTH_CHECK"
else
    echo -e "${RED}❌ Backend is not responding${NC}"
    echo "   Response: $HEALTH_CHECK"
    echo ""
    echo "   To start the backend:"
    echo "   cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend"
    echo "   python3 main.py"
    exit 1
fi
echo ""

# Step 2: Check CORS configuration
echo "🔒 Step 2: Checking CORS configuration..."
if grep -q "CORSMiddleware" /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend/main.py; then
    echo -e "${GREEN}✅ CORS middleware is configured${NC}"
else
    echo -e "${RED}❌ CORS middleware is missing${NC}"
fi
echo ""

# Step 3: Check backend logs
echo "📋 Step 3: Checking backend logs (last 10 lines)..."
if [ -f /tmp/fundiq_backend.log ]; then
    echo "Recent logs:"
    tail -10 /tmp/fundiq_backend.log | grep -i "error\|warn\|started" || echo "No errors found"
else
    echo -e "${YELLOW}⚠️  Backend log file not found${NC}"
fi
echo ""

# Step 4: Check .env.local
echo "📝 Step 4: Checking environment configuration..."
if [ -f /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local ]; then
    echo -e "${GREEN}✅ .env.local file exists${NC}"
    if grep -q "NEXT_PUBLIC_PARSER_API_URL" /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local; then
        echo "   API URL: $(grep NEXT_PUBLIC_PARSER_API_URL /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local | cut -d'=' -f2)"
    fi
else
    echo -e "${RED}❌ .env.local file not found${NC}"
    echo "   Creating it now..."
    cat > /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local << 'EOF'
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000
USE_SUPABASE=false
EOF
    echo -e "${GREEN}✅ Created .env.local${NC}"
fi
echo ""

# Step 5: Check frontend port
echo "🌐 Step 5: Checking frontend availability..."
FRONTEND_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>&1)
if [ "$FRONTEND_RESPONSE" = "200" ]; then
    echo -e "${GREEN}✅ Frontend is running on port 3000${NC}"
else
    echo -e "${YELLOW}⚠️  Frontend may not be running (HTTP $FRONTEND_RESPONSE)${NC}"
    echo "   To start the frontend:"
    echo "   cd /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel"
    echo "   npm run dev"
fi
echo ""

# Step 6: Test API endpoints
echo "🧪 Step 6: Testing API endpoints..."
echo "   Testing /documents endpoint..."
DOCS_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/documents 2>&1)
if [ "$DOCS_RESPONSE" = "200" ]; then
    echo -e "${GREEN}✅ /documents endpoint is working${NC}"
else
    echo -e "${RED}❌ /documents endpoint returned HTTP $DOCS_RESPONSE${NC}"
fi

echo ""
echo "📊 Summary:"
echo "==========="
echo "Backend: $(curl -s http://127.0.0.1:8000/health > /dev/null && echo '✅ Running' || echo '❌ Not running')"
echo "Frontend: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 | grep -q '200' && echo '✅ Running' || echo '❌ Not running')"
echo "CORS: $(grep -q CORSMiddleware /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/backend/main.py && echo '✅ Configured' || echo '❌ Missing')"
echo ".env.local: $([ -f /Users/mbakswatu/Desktop/Fintelligence/FundIQ/Tunnel/.env.local ] && echo '✅ Exists' || echo '❌ Missing')"
echo ""
echo "🎉 Debug check complete!"
echo ""
echo "If issues persist:"
echo "1. Clear Next.js cache: rm -rf .next"
echo "2. Restart frontend: npm run dev"
echo "3. Check browser console for errors"

