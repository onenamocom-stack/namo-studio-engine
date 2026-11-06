#!/usr/bin/env python3
"""Every gate must refuse the defect it was written for, and refuse loudly.

Run: python3 tests/test_gates.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "namo"))
import gates  # noqa: E402

sys.exit(gates._selftest())
