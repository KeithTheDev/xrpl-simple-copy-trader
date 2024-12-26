#!/bin/zsh
# Using zsh because only pagans use bash... and we're not from "the Industrial North" of shell scripting

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
    echo "Usage: ./start.sh [options]"
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
    
    if ! command -v "$python_cmd" >/dev/null 2>&1; then
        echo -e "${RED}Error: python3 not found${NC}"
        echo "Please install Python 3 using Homebrew:"
        echo "  brew install python"
        exit 1
    fi
    
    if ! "$python_cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
        echo -e "${RED}Error: Python 3.10 or newer is required${NC}"
        echo "Please update Python 3 using Homebrew:"
        echo "  brew upgrade python"
        exit 1
    fi
    
    echo "$python_cmd"
}

# Parse command line arguments
while (( $# > 0 )); do
    case "$1" in
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

# Get Python command
PYTHON_CMD="$(check_python)"
echo -e "${BLUE}Using Python: $($PYTHON_CMD --version)${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_CMD" -m venv venv
    source venv/bin/activate
    echo "Installing requirements..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Get Python from venv
VENV_PY="$(which python3)"

# Build array of arguments
ARGS=("web_server.py" "--port" "$PORT")
if [ "$DEBUG" = true ]; then
    ARGS+=("--debug")
fi
if [ "$TEST_MODE" = true ]; then
    ARGS+=("--test")
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

# Run the server
"$VENV_PY" "${ARGS[@]}"

# Keep window open if double-clicked
if [[ -z "${TERM_PROGRAM}" ]]; then
    echo -e "${BLUE}Press any key to exit...${NC}"
    read -n 1
fi