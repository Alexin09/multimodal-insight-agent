#!/bin/bash
# MultiModal Insight Agent — one-command startup
# Usage: ./start.sh

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║   MultiModal Insight Agent            ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""
echo "  Backend  → http://localhost:8000"
echo "  Frontend → http://localhost:3210"
echo ""

# ── Check .env ──
if [ ! -f "$DIR/backend/.env" ]; then
    echo "⚠️  No backend/.env found!"
    echo "   Copy the template and fill in your API keys:"
    echo ""
    echo "   cp backend/.env.example backend/.env"
    echo "   vim backend/.env"
    echo ""
    exit 1
fi

# ── Setup backend venv if needed ──
if [ ! -d "$DIR/backend/.venv" ]; then
    echo "⚙️  First run — creating Python virtual environment..."
    cd "$DIR/backend"
    python3 -m venv .venv
    echo "⚙️  Installing dependencies..."
    .venv/bin/pip install --trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org -q -r requirements.txt
    echo "✅ Backend dependencies installed"
    echo ""
fi

# ── Start both services ──
trap 'kill 0' INT TERM

echo "🚀 Starting backend (FastAPI on :8000)..."
cd "$DIR/backend" && .venv/bin/python server.py </dev/null &

# Wait for backend to be ready
echo "⏳ Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ Backend is ready"
        break
    fi
    sleep 1
done

echo "🚀 Starting frontend proxy (on :3210)..."
cd "$DIR" && python3 serve.py </dev/null &

echo ""
echo "✅ All services running!"
echo "   Open http://localhost:3210 in your browser"
echo "   Press Ctrl+C to stop"
echo ""

wait
