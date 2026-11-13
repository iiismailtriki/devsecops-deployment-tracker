"""Temporary fixture for testing AI-driven CI remediation."""

import sys
import os


def platform_info():
    return f"{os.name}:{sys.platform}"
