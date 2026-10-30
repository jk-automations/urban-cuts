"""Urban Cuts for ComfyUI: an open clone of Higgsfield's Urban Cuts app. One person photo + 3 to 5 outfits or products
+ music -> a 9:16 reel that cuts on the beat and loops. Clone into ComfyUI/custom_nodes/. Apache-2.0."""
from pathlib import Path

if __package__:  # loaded by ComfyUI as a custom node pack (pytest imports this file without a package)
    from .urban_nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
else:
    NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = {}, {}

BLANK = "urban_blank.png"

# Unused look slots still need a file: put a flat placeholder into input/ (Beat Cut skips flat images).
try:
    if not __package__:
        raise ImportError("not running inside ComfyUI")
    import folder_paths
    from PIL import Image
    _blank = Path(folder_paths.get_input_directory()) / BLANK
    if not _blank.exists():
        _blank.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (255, 255, 255)).save(_blank)
except Exception as e:  # never block ComfyUI start-up
    print(f"[Urban Cuts] could not place the blank placeholder: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
