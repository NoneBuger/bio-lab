"""CLI entry point for the basic QC workflow."""

import argparse

from app.qc import run_qc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input .h5ad file")
    parser.add_argument("output", help="Output directory")
    args = parser.parse_args()
    print(run_qc(args.input, args.output))


if __name__ == "__main__":
    main()
