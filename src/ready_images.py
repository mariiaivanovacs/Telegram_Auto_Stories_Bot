"""
Manages the ready_images/ folder — pre-processed backgrounds for story rendering.

Workflow: admin uploads a photo → process_and_store() crops, enhances, and darkens it
→ stored as a ready PNG. /run_step_3 then uses these instead of raw backgrounds.
"""
import logging
import random
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

READY_DIR = "ready_images"
_IMG_EXTS = {".jpg", ".jpeg", ".png"}


def process_and_store(source_path: str, ready_dir: str = READY_DIR) -> str:
    """Process one background image and save it to ready_dir. Returns saved path."""
    from src.story import _prepare_story_background

    Path(ready_dir).mkdir(parents=True, exist_ok=True)
    stem = Path(source_path).stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(ready_dir) / f"{stem}_{ts}.png"

    img = _prepare_story_background(source_path)
    img.convert("RGB").save(str(out_path), "PNG", optimize=True)
    logger.info("Ready image saved: %s", out_path)
    return str(out_path)


def list_images(ready_dir: str = READY_DIR) -> list[dict]:
    """Return all ready images sorted by name. Each dict has id (1-based), name, path."""
    d = Path(ready_dir)
    if not d.exists():
        return []
    files = sorted(f for f in d.iterdir() if f.suffix.lower() in _IMG_EXTS)
    return [{"id": i + 1, "name": f.name, "path": str(f)} for i, f in enumerate(files)]


def delete_image(identifier: str, ready_dir: str = READY_DIR) -> str | None:
    """Delete by 1-based index or filename. Returns deleted filename, or None if not found."""
    images = list_images(ready_dir)
    target = None
    try:
        idx = int(identifier)
        if 1 <= idx <= len(images):
            target = images[idx - 1]
    except ValueError:
        pass
    if target is None:
        for img in images:
            if img["name"] == identifier:
                target = img
                break
    if target is None:
        return None
    Path(target["path"]).unlink(missing_ok=True)
    logger.info("Ready image deleted: %s", target["name"])
    return target["name"]


def flush_images(ready_dir: str = READY_DIR) -> int:
    """Delete all ready images. Returns count deleted."""
    images = list_images(ready_dir)
    for img in images:
        Path(img["path"]).unlink(missing_ok=True)
    logger.info("Flushed %d ready image(s)", len(images))
    return len(images)


def process_backgrounds_dir(
    backgrounds_dir: str = "backgrounds",
    ready_dir: str = READY_DIR,
) -> tuple[list[str], list[str]]:
    """
    Process every image in backgrounds_dir and store results in ready_dir.
    Returns (saved_paths, failed_names).
    """
    sources = sorted(
        f for f in Path(backgrounds_dir).iterdir() if f.suffix.lower() in _IMG_EXTS
    )
    if not sources:
        return [], []

    saved: list[str] = []
    failed: list[str] = []
    for src in sources:
        try:
            path = process_and_store(str(src), ready_dir)
            saved.append(path)
        except Exception as exc:
            logger.error("Failed to process %s: %s", src.name, exc)
            failed.append(src.name)
    return saved, failed


def pick_for_render(ready_dir: str = READY_DIR, count: int = 3) -> list[str]:
    """Pick `count` paths from ready_dir at random. Returns empty list if folder is empty."""
    images = list_images(ready_dir)
    if not images:
        return []
    paths = [img["path"] for img in images]
    if len(paths) >= count:
        return random.sample(paths, count)
    return [random.choice(paths) for _ in range(count)]
