import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "namo"))
import gates
sys.exit(gates._selftest())
