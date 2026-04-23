from __future__ import annotations

import sys

from rtd2chunk_pipeline_pkg.runner import main


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "execute", *sys.argv[1:]]
    main()
    