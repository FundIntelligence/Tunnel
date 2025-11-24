#!/bin/bash

# FundIQ Service Role Key Test Runner
# This script runs all verification tests

echo "🧪 =================================================="
echo "   FundIQ Service Role Key Verification Tests"
echo "=================================================="
echo ""

# Check if we're in the backend directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: Please run this script from the backend directory"
    echo "   cd backend && bash RUN_TESTS.sh"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Error: Virtual environment not found"
    echo "   Run: python3 -m venv venv"
    exit 1
fi

# Activate virtual environment
echo "📦 Activating virtual environment..."
source venv/bin/activate

# Check if required packages are installed
echo "📦 Checking dependencies..."
python -c "import supabase, dotenv" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Missing dependencies. Installing..."
    pip install -r requirements.txt
fi

echo ""
echo "🔬 Running Service Role Key Tests..."
echo ""

# Run the test script
python test_service_role.py

# Capture exit code
TEST_RESULT=$?

echo ""
echo "=================================================="

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ All tests passed successfully!"
    echo ""
    echo "Next steps:"
    echo "  1. Start the backend: python main.py"
    echo "  2. Upload a file and check logs for [DEBUG] messages"
    echo "  3. Verify no RLS errors appear"
else
    echo "❌ Some tests failed. See errors above."
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check service_role key in main.py"
    echo "  2. Verify Supabase URL is correct"
    echo "  3. Ensure database tables exist (run schema.sql)"
    echo "  4. Check Supabase dashboard for RLS settings"
fi

echo "=================================================="
echo ""

exit $TEST_RESULT


