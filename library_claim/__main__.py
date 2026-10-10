"""Run an explicitly configured synthetic packet export."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from .demo import synthetic_fixture
from .models import PacketPolicy
from .packet import export_packet


def main():
    parser = argparse.ArgumentParser(description="M01 synthetic packet smoke test; no live services")
    parser.add_argument("--country", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--currency-decimal-places", required=True, type=int)
    parser.add_argument("--exclusion-basis", required=True, choices=["missing_any_component", "missing_all_components"])
    parser.add_argument("--shelf-run-basis", required=True, choices=["sum_spine_thickness"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    policy = PacketPolicy(currency_decimal_places=args.currency_decimal_places,
                          exclusion_basis=args.exclusion_basis, shelf_run_basis=args.shelf_run_basis)
    with TemporaryDirectory(prefix="library-claim-m01-") as temp:
        root = Path(temp)
        packet, report = export_packet(synthetic_fixture(root, args.country, args.currency), root, args.output, policy)
    print(f"Synthetic packet: {packet}\nReport: {report}")


if __name__ == "__main__":
    main()
