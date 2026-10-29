#!/usr/bin/python3
# Isolated Python startup, with only this root-owned application directory added.
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from server import main
main()
