"""Build a credential-free ZIP for friends without copying the repository."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lan_service import worker_archive

if __name__ == "__main__":
    target = ROOT / "lan/dist/Factory-Worker.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(worker_archive(ROOT).getvalue())
    print(target)
