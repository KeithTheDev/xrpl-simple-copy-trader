# xrpl_logger.py

import logging
import sys
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime

class XRPLLogger:
    """Unified logging utility for XRPL monitoring components"""
    
    # ANSI color codes
    COLORS = {
        'yellow': "\033[93m",
        'red': "\033[91m",
        'green': "\033[92m",
        'blue': "\033[94m",
        'purple': "\033[95m",
        'cyan': "\033[96m",
        'reset': "\033[0m"
    }

    # Emoji indicators
    EMOJIS = {
        'new_token': "🆕",
        'trust_line': "🔗",
        'hot_token': "🔥",
        'trade': "💰",
        'hot_trade': "💸",
        'alert': "⚠️",
        'success': "✅",
        'error': "❌",
        'warning': "⚡",
        'test': "🧪",
        'web': "🌐",
        'stats': "📊"
    }

    def __init__(self, 
                 name: str, 
                 log_file: Optional[str] = None,
                 log_level: str = "INFO",
                 debug: bool = False,
                 test_mode: bool = False,
                 use_colors: bool = True):
        """Initialize logger with specified configuration."""
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG if debug else getattr(logging, log_level.upper()))
        self.test_mode = test_mode
        self.use_colors = use_colors
        
        # Clear any existing handlers
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.DEBUG if debug else getattr(logging, log_level.upper()))
        self.logger.addHandler(console_handler)
        
        # File handler if specified
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(log_file)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.INFO)
            self.logger.addHandler(file_handler)

    def _colorize(self, text: str, color: str) -> str:
        """Add color to text if colors are enabled"""
        if self.use_colors:
            return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"
        return text

    def _format_message(self, msg: str, test_mode: bool = None) -> str:
        """Format message with test mode indicator if needed"""
        test_mode = test_mode if test_mode is not None else self.test_mode
        return f"{self.EMOJIS['test']} [TEST] {msg}" if test_mode else msg

    # Basic logging methods
    def debug(self, msg: str) -> None:
        """Log debug message"""
        self.logger.debug(self._format_message(msg))

    def info(self, msg: str) -> None:
        """Log info message"""
        self.logger.info(self._format_message(msg))

    def warning(self, msg: str) -> None:
        """Log warning with yellow color"""
        self.logger.warning(self._format_message(self._colorize(msg, 'yellow')))

    def error(self, msg: str) -> None:
        """Log error with red color"""
        self.logger.error(self._format_message(self._colorize(msg, 'red')))

    def success(self, msg: str) -> None:
        """Log success message with green color"""
        self.logger.info(self._format_message(self._colorize(msg, 'green')))

    # Error handling methods
    def error_with_context(self, error_type: str, error: Exception,
                          context: str = "") -> None:
        """Log error with additional context"""
        msg = [
            f"\n{self.EMOJIS['error']} Error in {error_type}: {str(error)}"
        ]
        if context:
            msg.append(f"Context: {context}")
        msg.append("")
        self.error("\n".join(msg))

    def log_error(self, error: str, context: str = "") -> None:
        """Alternative method for logging errors"""
        self.error_with_context("operation", Exception(error), context)

    # Token-related logging methods
    def log_token_discovery(self, currency: str, issuer: str, value: str,
                          test_mode: Optional[bool] = None) -> None:
        """Log new token discovery"""
        msg = [
            f"\n{self.EMOJIS['new_token']} New token discovered!",
            f"   Currency: {currency}",
            f"   Issuer: {issuer}",
            f"   First trust line value: {value}\n"
        ]
        self.info("\n".join(msg))

    def log_trust_line_update(self, currency: str, issuer: str, 
                            trust_lines: int, removed: bool = False,
                            test_mode: Optional[bool] = None) -> None:
        """Log trust line changes"""
        action = "removed from" if removed else "added to"
        msg = [
            f"\n{self.EMOJIS['trust_line']} Trust line {action} {currency}",
            f"   Issuer: {issuer}",
            f"   Current trust lines: {trust_lines}\n"
        ]
        self.info("\n".join(msg))

    def log_hot_token(self, currency: str, issuer: str, 
                     trust_lines: int, time_to_hot: datetime,
                     test_mode: Optional[bool] = None) -> None:
        """Log when token reaches 'hot' status"""
        msg = [
            f"\n{self.EMOJIS['hot_token']} Token reached {trust_lines} trust lines!",
            f"   Currency: {currency}",
            f"   Issuer: {issuer}",
            f"   Time to reach threshold: {time_to_hot}\n"
        ]
        self.success("\n".join(msg))

    def log_trade(self, currency: str, issuer: str, amount: str,
                 total_volume: str, total_trades: int, trust_lines: int,
                 is_hot: bool = False, test_mode: Optional[bool] = None) -> None:
        """Log trading activity"""
        emoji = self.EMOJIS['hot_trade'] if is_hot else self.EMOJIS['trade']
        prefix = "Hot token" if is_hot else "Token"
        msg = [
            f"\n{emoji} {prefix} traded!",
            f"   Currency: {currency}",
            f"   Amount: {amount}",
            f"   Total volume: {total_volume}",
            f"   Total trades: {total_trades}"
        ]
        if trust_lines:
            msg.append(f"   Trust lines: {trust_lines}")
        msg.append("")
        self.info("\n".join(msg))

    # Status and monitoring logging
    def log_status_update(self, total_tokens: int, hot_tokens: int,
                         token_details: List[str] = None) -> None:
        """Log periodic status update"""
        status = [
            f"{self._colorize('='*50, 'yellow')}",
            f"Status Update ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            f"{'='*50}",
            f"Tracking {total_tokens} tokens total",
            f"Hot tokens: {hot_tokens}"
        ]

        if token_details:
            status.append("\nHot Token Details:")
            status.extend(token_details)

        status.extend([f"\n{'='*50}"])
        self.info("\n".join(status))

    def log_connection_status(self, status: str, extra_info: str = "") -> None:
        """Log WebSocket connection status"""
        messages = {
            "connecting": (f"Connecting to {extra_info}", 'info'),
            "connected": ("Connected to XRPL", 'success'),
            "disconnected": (f"Disconnected: {extra_info}", 'warning'),
            "reconnecting": (f"Reconnecting... {extra_info}", 'info')
        }
        
        msg, level = messages.get(status, (f"Unknown status: {status}", 'warning'))
        getattr(self, level)(msg)

    # Debugging methods
    def log_debug_transaction(self, tx_type: str, tx_hash: str,
                            details: Dict[str, Any]) -> None:
        """Log transaction details for debugging"""
        if self.logger.isEnabledFor(logging.DEBUG):
            msg = [
                f"\n{self.EMOJIS['stats']} Transaction Details:",
                f"   Type: {tx_type}",
                f"   Hash: {tx_hash}"
            ]
            for key, value in details.items():
                msg.append(f"   {key}: {value}")
            msg.append("")
            self.debug("\n".join(msg))