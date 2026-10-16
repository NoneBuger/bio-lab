"""CLI compatibility wrapper for the app-local omics-scientist evaluator."""

import argparse

from app.omics_scientist import assess_qc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input .h5ad file")
    parser.add_argument("output", help="Markdown report path")
    args = parser.parse_args()
    print(assess_qc(args.input, args.output))


if __name__ == "__main__":
    main()
