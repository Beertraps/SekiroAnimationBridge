"""Compatibility entry point for extracting a single FLVER preview."""
import argparse
from pathlib import Path
from flver_geometry import extract_flver

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('flver',type=Path); parser.add_argument('output',type=Path)
    args=parser.parse_args(); extract_flver(args.flver,args.output)
