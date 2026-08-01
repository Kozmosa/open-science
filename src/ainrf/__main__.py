from __future__ import annotations

import os
import sys


def main() -> None:
    os.execvp("ainrf", ["ainrf", *sys.argv[1:]])


if __name__ == "__main__":
    main()
