from pathlib import Path
import sys


CURRENT_DIR = Path(__file__).resolve().parent
UI_DIR = CURRENT_DIR / "ui"

if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

from app import main


if __name__ == "__main__":
    raise SystemExit(main())
