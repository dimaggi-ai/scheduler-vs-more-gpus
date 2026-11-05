"""Agent-callable, offline synthetic coupled-state feasibility kernel."""
VERSION = '0.1.0'
from .kernel import evaluate
__all__ = ['evaluate', 'VERSION']
