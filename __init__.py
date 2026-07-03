from .tagged_image_batch_loader import TaggedImageBatchLoader
from .tagged_image_dual_loader import TaggedImageDualLoader

NODE_CLASS_MAPPINGS = {
    "TaggedImageBatchLoader": TaggedImageBatchLoader,
    "TaggedImageDualLoader": TaggedImageDualLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TaggedImageBatchLoader": "Tagged Image Batch Loader",
    "TaggedImageDualLoader": "Tagged Image Dual Loader",
}

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
