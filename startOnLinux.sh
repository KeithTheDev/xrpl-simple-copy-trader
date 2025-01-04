#!/usr/bin/env bash
# A Bash script for starting the "XRPL Token Monitor" on a modern Ubuntu system.
# It checks Python, checks if MongoDB is running, creates/activates a virtual environment,
# reads command-line flags, and launches either the web interface or the memecoin monitor.

# Color codes for nice-looking output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default settings
PORT=8000
DEBUG=false
TEST_MODE=false
MODE="web"  # Default mode is 'web'

# Change to the directory where the script is located
cd "$(dirname "$0")"

# Help function
show_help() {
    echo "XRPL Token Monitor"
    echo
    echo "Usage: ./start_ubuntu.sh [options] [mode]"
    echo
    echo "Modes:"
    echo "  web       Start the web interface (default)"
    echo "  memecoin  Start the memecoin monitor directly"
    echo
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -p, --port PORT     Set the port for the web interface (default: 8000)"
    echo "  -d, --debug         Enable debug mode"
    echo "  -t, --test          Enable test mode (no real transactions)"
    echo
}

# Check Python version
check_python() {
    local python_cmd="python3"

    if ! command -v "$python_cmd" >/dev/null 2>&1; then
        echo -e "${RED}Error: Python 3 is not installed${NC}"
        echo "Install it via: sudo apt-get update && sudo apt-get install python3"
        exit 1
    fi

    # Require Python 3.10 or newer
    if ! "$python_cmd" -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"; then
        echo -e "${RED}Error: Python 3.10 or newer is required${NC}"
        echo "You can install or update it with: sudo apt-get update && sudo apt-get install python3.10"
        exit 1
    fi

    echo "$python_cmd"
}

# Check that MongoDB is running
check_mongodb() {
    # On Ubuntu, the service name is often 'mongod'
    local service_name="mongod"

    if ! systemctl is-active --quiet "$service_name"; then
        echo -e "${RED}MongoDB (service name '${service_name}') is not running${NC}"
        echo "Start the service: sudo systemctl start $service_name"
        echo "Or install it via: sudo apt-get update && sudo apt-get install mongodb"
        exit 1
    fi
}

# Parse command-line arguments
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
        web|memecoin)
            MODE="$1"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Get the Python command
PYTHON_CMD="$(check_python)"
echo -e "${BLUE}Using Python: $($PYTHON_CMD --version)${NC}"

# Check if MongoDB is running
check_mongodb

# Create or activate the virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    "$PYTHON_CMD" -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# Get the Python interpreter from the virtual environment
VENV_PY="$(which python3)"

# Determine which script and arguments to use based on the mode
case "$MODE" in
    web)
        SCRIPT="web_server.py"
        ARGS=("--port" "$PORT")
        ;;
    memecoin)
        SCRIPT="memecoin_monitor.py"
        ARGS=()
        ;;
esac

# Append debug and test flags if enabled
if [ "$DEBUG" = true ]; then
    ARGS+=("--debug")
fi
if [ "$TEST_MODE" = true ]; then
    ARGS+=("--test")
fi

# Print startup info
echo -e "${GREEN}Starting XRPL Token Monitor in '$MODE' mode${NC}"
echo -e "${BLUE}Configuration:${NC}"
echo "  Mode: $MODE"
[ "$MODE" = "web" ] && echo "  Port: $PORT"
echo "  Debug mode: $DEBUG"
echo "  Test mode: $TEST_MODE"
echo

if [ "$MODE" = "web" ]; then
    echo -e "${BLUE}When the server starts, open your browser at:${NC}"
    echo "  http://localhost:$PORT"
    echo
fi

# Launch the chosen script
"$VENV_PY" "$SCRIPT" "${ARGS[@]}"

# Keep the window open if there's no terminal
if [[ -z "${TERM_PROGRAM}" ]]; then
    echo -e "${BLUE}Press any key to exit...${NC}"
    read -n 1
fi