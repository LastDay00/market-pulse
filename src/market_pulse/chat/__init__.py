"""Chat Claude spécialisé finance, intégré à l'écran détail."""
from market_pulse.chat.availability import check_claude_available
from market_pulse.chat.client import ChatSession

__all__ = ["check_claude_available", "ChatSession"]
