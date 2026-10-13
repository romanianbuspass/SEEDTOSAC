#!/usr/bin/env python3
"""Dedicated PyInstaller entry point for mseed2sac-gui."""
from __future__ import annotations

import sys

from mseed2sac_gui import main

if __name__ == "__main__":
    sys.exit(main())
