"""Make `import hsflow` work in tests without installing the package.

For real use, prefer `pip install -e .`; this shim just keeps `pytest` runnable
straight from a fresh clone.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
