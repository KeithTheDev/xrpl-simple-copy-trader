#!/bin/bash
# Using bash because this is Linux and we're practical people here

# Colors for pretty output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default values
PORT=8000
DEBUG=false
TEST_MODE=false

# Change to script directory
cd "$(dirname "$0")"

# Help function
show_help() {
    echo "XRPL Token Monitor"
    echo
    echo "Usage: ./startOnLinux.sh [options]"
    echo
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -p, --port PORT     Set web interface port (default: 8000)"
    echo "  -d, --debug         Enable debug mode"
    echo "  -t, --test          Enable test mode (no real transactions)"
    echo
}

# Check Python version
check_python() {
    local python_cmd="python3"
    
    if ! command -v $python_cmd >/dev/null 2>&1; then
        echo -e "${RED}Error: python3 not found${NC}"
        echo "Please install Python 3 using your package manager:"
        echo "  Ubuntu/Debian: sudo apt install python3"
        echo "  Fedora: sudo dnf install python3"
        echo "  Arch: sudo pacman -S python"
        exit 1
    fi
    
    if ! $python_cmd -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
        echo -e "${RED}Error: Python 3.10 or newer is required${NC}"
        echo "Please update Python 3 using your package manager"
        exit 1
    fi
    
    echo $python_cmd
}

# Parse command line arguments
while [ $# -gt 0 ]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -d|--debug)
            DEBUG=true
            shift
            ;;
        -t|--test)
            TEST_MODE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Get appropriate Python command
PYTHON_CMD=$(check_python)
echo -e "${BLUE}Using Python: $($PYTHON_CMD --version)${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
    source venv/bin/activate
    echo "Installing requirements..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Build command with options
CMD="$PYTHON_CMD web_server.py --port $PORT"
if [ "$DEBUG" = true ]; then
    CMD="$CMD --debug"
fi
if [ "$TEST_MODE" = true ]; then
    CMD="$CMD --test"
fi

# Print startup information
echo -e "${GREEN}Starting XRPL Token Monitor${NC}"
echo -e "${BLUE}Configuration:${NC}"
echo "  Port: $PORT"
echo "  Debug mode: $DEBUG"
echo "  Test mode: $TEST_MODE"
echo
echo -e "${BLUE}When started, open your browser at:${NC}"
echo "  http://localhost:$PORT"
echo

# Execute the monitor
$CMD