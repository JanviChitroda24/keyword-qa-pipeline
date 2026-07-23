#!/usr/bin/env python3
"""Thin wrapper — forwards all args to the main keyword QA CLI in 10_keyword_setup/."""
import runpy
import sys
from pathlib import Path
sys.argv[0] = str(Path(__file__).resolve().parent.parent / "10_keyword_setup" / "ensemble_pipeline_v2.py")
runpy.run_path(str(Path(__file__).resolve().parent.parent / "10_keyword_setup" / "ensemble_pipeline_v2.py"), run_name="__main__")
