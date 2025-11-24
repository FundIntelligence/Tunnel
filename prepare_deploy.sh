#!/bin/bash

# 🚀 Prepare for Production Deployment
# This script prepares your local environment for Railway + Vercel deployment

echo "🚀 =================================================="
echo "   FundIQ - Production Deployment Preparation"
echo "=================================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Step 1: Kill all local processes
echo -e "${BLUE}Step 1: Killing all local development processes...${NC}"
lsof -ti:3000,3001,8000,8001,8002 | xargs kill -9 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ All local processes killed${NC}"
else
    echo -e "${GREEN}✅ No local processes running${NC}"
fi
echo ""

# Step 2: Clean up local files
echo -e "${BLUE}Step 2: Cleaning up local development files...${NC}"
rm -f .env.local 2>/dev/null
rm -f backend.log frontend.log 2>/dev/null
echo -e "${GREEN}✅ Local files cleaned${NC}"
echo ""

# Step 3: Create Railway configuration
echo -e "${BLUE}Step 3: Creating Railway configuration...${NC}"
cd backend
cat > railway.toml << 'EOF'
[build]
builder = "nixpacks"
buildCommand = "pip install -r requirements.txt"

[deploy]
startCommand = "uvicorn main:app --host 0.0.0.0 --port $PORT"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 10
EOF
cd ..
echo -e "${GREEN}✅ railway.toml created${NC}"
echo ""

# Step 4: Create production environment template
echo -e "${BLUE}Step 4: Creating production environment template...${NC}"
cat > .env.production.template << 'EOF'
# RAILWAY ENVIRONMENT VARIABLES (Backend)
SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDAxOTIyNywiZXhwIjoyMDc1NTk1MjI3fQ.86MoLq3YsR9bPUSoJTZkAxrFHI2XWfGRMV8y68xpVX8

# VERCEL ENVIRONMENT VARIABLES (Frontend)
NEXT_PUBLIC_API_URL=https://YOUR-RAILWAY-URL.up.railway.app
NEXT_PUBLIC_SUPABASE_URL=https://caajasgudqsqlztjqedc.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNhYWphc2d1ZHFzcWx6dGpxZWRjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjAwMTkyMjcsImV4cCI6MjA3NTU5NTIyN30.nwKkTwmhS_dJTMb7KxhKIEYZWvfZ8pDLRH3iyLgQaT4
NEXT_PUBLIC_PARSER_API_URL=https://YOUR-RAILWAY-URL.up.railway.app
EOF
echo -e "${GREEN}✅ .env.production.template created${NC}"
echo ""

# Step 5: Check Git status
echo -e "${BLUE}Step 5: Checking Git status...${NC}"
cd /Users/mbakswatu/Desktop/Fintelligence
if git rev-parse --git-dir > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Git repository detected${NC}"
    
    # Show status
    echo ""
    git status --short
    echo ""
    
    # Ask to commit
    echo -e "${YELLOW}📝 Ready to commit changes?${NC}"
    echo "   Run: git add . && git commit -m 'Prepare for production deployment' && git push"
else
    echo -e "${RED}❌ Not a Git repository${NC}"
    echo "   Initialize Git first: git init"
fi
echo ""

# Step 6: Display next steps
echo "=================================================="
echo -e "${GREEN}✅ PREPARATION COMPLETE!${NC}"
echo "=================================================="
echo ""
echo -e "${BLUE}📋 Next Steps:${NC}"
echo ""
echo "1️⃣  Commit and push to GitHub:"
echo "   cd /Users/mbakswatu/Desktop/Fintelligence"
echo "   git add ."
echo "   git commit -m 'Prepare for production deployment'"
echo "   git push origin main"
echo ""
echo "2️⃣  Deploy Backend to Railway:"
echo "   → Go to: https://railway.app/dashboard"
echo "   → New Project → Deploy from GitHub"
echo "   → Select: Fintelligence repo"
echo "   → Root: FundIQ/Tunnel/backend"
echo "   → Add environment variables from .env.production.template"
echo "   → Deploy!"
echo ""
echo "3️⃣  Deploy Frontend to Vercel:"
echo "   → Go to: https://vercel.com/new"
echo "   → Import GitHub repo"
echo "   → Root: FundIQ/Tunnel"
echo "   → Add environment variables from .env.production.template"
echo "   → Replace YOUR-RAILWAY-URL with actual Railway URL"
echo "   → Deploy!"
echo ""
echo "4️⃣  Update CORS in backend/main.py:"
echo "   → Add your Vercel URL to allow_origins"
echo "   → Push to GitHub (Railway auto-redeploys)"
echo ""
echo "5️⃣  Test Production:"
echo "   → curl https://YOUR-RAILWAY-URL.up.railway.app/health"
echo "   → Open https://YOUR-VERCEL-URL.vercel.app"
echo "   → Upload a test file"
echo ""
echo "📚 See DEPLOY_TO_PRODUCTION.md for detailed guide"
echo "📋 See DEPLOY_CHECKLIST.md for step-by-step checklist"
echo ""
echo "=================================================="
echo ""




