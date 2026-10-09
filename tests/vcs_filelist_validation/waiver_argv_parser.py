#!/usr/bin/env python3
"""Record the generated lint launcher's exact parser arguments."""

import json
import os
from pathlib import Path
import sys

Path(os.environ["WAIVER_ARGV_LOG"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
