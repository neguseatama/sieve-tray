from __future__ import annotations

import argparse
import json
import sys

from .observer import make_machine_receipt, make_receipt, observe


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe a prompt and print its receipt.")
    parser.add_argument("prompt", nargs="?", help="prompt text; reads stdin when omitted")
    parser.add_argument("--json", action="store_true", dest="machine", help="print the machine receipt")
    args = parser.parse_args()
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    observation = observe(prompt)
    print(make_machine_receipt(observation) if args.machine else make_receipt(observation, prompt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
