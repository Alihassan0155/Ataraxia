"""Run from repository root: python -m research.recommendation.demo."""
import argparse
import json
from pathlib import Path
from .catalogue import DEFAULT_DATABASE, load_local_database, load_local_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--database', default=DEFAULT_DATABASE, help='Local /tmp PostgreSQL database name')
    source.add_argument('--package', type=Path, help='Existing checksummed local catalogue package')
    parser.add_argument('--report', type=Path, help='Write full report to a NEW private local file')
    args = parser.parse_args()
    catalogue = load_local_package(args.package) if args.package else load_local_database(args.database)
    if args.report:
        with args.report.open('x', encoding='utf-8') as file:
            json.dump(catalogue.report, file, indent=2, allow_nan=False)
            file.write('\n')
    print(json.dumps({k: v for k, v in catalogue.report.items() if k != 'excluded_records'}, indent=2))


if __name__ == '__main__':
    main()
