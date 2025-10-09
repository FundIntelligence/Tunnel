#!/bin/bash

# FundIQ MVP - Quick Start Script
# This script helps you get started quickly

echo "🚀 FundIQ MVP Quick Start"
echo "=========================="
echo ""

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    echo "   Visit: https://nodejs.org"
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.9+ first."
    echo "   Visit: https://www.python.org"
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo "✅ Python version: $(python3 --version)"
echo ""

# Check if .env.local exists
if [ ! -f ".env.local" ]; then
    echo "⚠️  .env.local not found!"
    echo "   Creating from template..."
    echo ""
    echo "NEXT_PUBLIC_SUPABASE_URL=your-supabase-url" > .env.local
    echo "NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key" >> .env.local
    echo "NEXT_PUBLIC_PARSER_API_URL=http://localhost:8000" >> .env.local
    echo ""
    echo "📝 Please edit .env.local and add your Supabase credentials"
    echo "   Then run this script again."
    exit 0
fi

# Check if backend/.env exists
if [ ! -f "backend/.env" ]; then
    echo "⚠️  backend/.env not found!"
    echo "   Creating from template..."
    echo ""
    echo "SUPABASE_URL=your-supabase-url" > backend/.env
    echo "SUPABASE_SERVICE_ROLE_KEY=your-service-role-key" >> backend/.env
    echo ""
    echo "📝 Please edit backend/.env and add your Supabase credentials"
    echo "   Then run this script again."
    exit 0
fi

echo "🔧 Installing dependencies..."
echo ""

# Install frontend dependencies
echo "📦 Installing frontend dependencies..."
npm install
if [ $? -ne 0 ]; then
    echo "❌ Failed to install frontend dependencies"
    exit 1
fi

# Set up Python virtual environment
echo ""
echo "🐍 Setting up Python environment..."
cd backend

if [ ! -d "venv" ]; then
    echo "   Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment and install dependencies
echo "   Installing Python dependencies..."
source venv/bin/activate
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "❌ Failed to install Python dependencies"
    exit 1
fi

cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "🎯 Next steps:"
echo ""
echo "1. Make sure you've set up Supabase:"
echo "   - Created a project"
echo "   - Run the schema.sql in SQL Editor"
echo "   - Created 'uploads' storage bucket"
echo ""
echo "2. Start the backend (in one terminal):"
echo "   cd backend"
echo "   source venv/bin/activate"
echo "   uvicorn main:app --reload"
echo ""
echo "3. Start the frontend (in another terminal):"
echo "   npm run dev"
echo ""
echo "4. Open http://localhost:3000 in your browser"
echo ""
echo "📚 For detailed setup instructions, see SETUP.md"
echo ""


