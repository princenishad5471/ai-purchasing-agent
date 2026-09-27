#!/bin/bash

echo "🚀 AI Purchasing Agent - Quick Start"
echo "===================================="
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install backend dependencies
echo "📦 Installing backend dependencies..."
pip install -q -r backend/requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "To start the application:"
echo ""
echo "1. Backend:"
echo "   cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "2. Frontend (in a new terminal):"
echo "   cd frontend && npm install && npm run dev"
echo ""
echo "3. Run tests:"
echo "   source venv/bin/activate && python tests/test_scenarios.py"
echo ""
echo "4. Access:"
echo "   - Frontend: http://localhost:3000"
echo "   - Backend API: http://localhost:8000"
echo "   - API Docs: http://localhost:8000/docs"
echo ""
