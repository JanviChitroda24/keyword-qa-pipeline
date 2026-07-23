#!/usr/bin/env python3
"""Thin wrapper — forwards all args to the main acronym QA CLI in 21_acronym_setup/."""
import runpy
import sys
from pathlib import Path
sys.argv[0] = str(Path(__file__).resolve().parent.parent / "21_acronym_setup" / "acronym_pipeline.py")
runpy.run_path(str(Path(__file__).resolve().parent.parent / "21_acronym_setup" / "acronym_pipeline.py"), run_name="__main__")
