"""dmxreplay-convert CLI. Not implemented yet: brief §51 lists it, but its
exact conversion options (re-encode to a different pixel encoding? remap
universes into a new file? change fps?) were never specified. Deferred until
a concrete need defines the scope, rather than guessing at options now."""
from __future__ import annotations

import sys


def main() -> None:
    print("dmxreplay-convert is not implemented yet.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
