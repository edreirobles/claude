"""
Entry point del Trading Agent USD/MXN
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.core import run_agent

if __name__ == "__main__":
    run_agent()
