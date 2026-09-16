import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SRC = HERE.parents[1] / "src"
USA_SRC = HERE.parents[2] / "usaspending" / "src"
for p in (SRC, USA_SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
