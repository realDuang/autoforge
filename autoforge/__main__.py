"""AutoForge entry point: python -m autoforge"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoforge.orchestrator import main

if __name__ == "__main__":
    main()
