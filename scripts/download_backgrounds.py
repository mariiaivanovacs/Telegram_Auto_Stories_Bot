"""
One-time script to download background images from Google Drive into backgrounds/.
Uses gdown — installed automatically if missing.
"""
import subprocess
import sys
from pathlib import Path

FOLDER_URL = "https://drive.google.com/drive/folders/1P0Ajk13ltRw8HmT-6bjqeWaR89v9vZ15"
DEST = "backgrounds/"


def main():
    try:
        import gdown  # noqa: F401
    except ImportError:
        print("gdown not found — installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gdown", "-q"])
        import gdown  # noqa: F401

    import gdown as gd

    Path(DEST).mkdir(exist_ok=True)
    print(f"Downloading backgrounds from Google Drive → {DEST}")
    gd.download_folder(FOLDER_URL, output=DEST, quiet=False, use_cookies=False)
    files = list(Path(DEST).glob("*.jpg")) + list(Path(DEST).glob("*.png"))
    print(f"✓ {len(files)} background(s) saved to {DEST}")


if __name__ == "__main__":
    main()
