"""
parity_analysis_runner.py - Python equivalent of parity_analysis_runner.rs.

Output format: one key\ttabvalue per line, matching the Rust binary exactly.
"""

import sys
import os

# Add project root to path so `bridge` is findable regardless of cwd
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))              # crates/parity/python
PARENT1 = os.path.dirname(SCRIPT_DIR)                              # crates/parity
PARENT2 = os.path.dirname(PARENT1)                                  # project root directory
# The project root is PARENT2, but it might be nested; find the one with pyproject/Cargo.toml
# For now, just add the direct parent of crates
PROJECT_ROOT = os.path.dirname(PARENT1)  # This gives the actual project root
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bridge import analysis_runner
from bridge import measurements