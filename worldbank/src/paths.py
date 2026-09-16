"""Shared paths for the worldbank workstream."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WS = REPO / "worldbank"
RAW = REPO / "data" / "raw" / "worldbank"
WDS = RAW / "wds"
PROJECTS = RAW / "projects"
IEG = RAW / "ieg"
PAD_TEXT = RAW / "pad_text"
RESULTS = WS / "results"
LOGS = WS / "logs"

for _p in (WDS, PROJECTS, IEG, PAD_TEXT, RESULTS, LOGS):
    _p.mkdir(parents=True, exist_ok=True)

IEG_CSV = IEG / "IEG_World_Bank_Project_Performance_Ratings.csv"
IEG_URL = (
    "https://financesonefiles.worldbank.org/f-one/DS00053/RS00055/"
    "IEG_World_Bank_Project_Performance_Ratings.csv"
)
