from .tagged_image_batch_loader import TaggedImageBatchLoader

NODE_CLASS_MAPPINGS = {
    "TaggedImageBatchLoader": TaggedImageBatchLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TaggedImageBatchLoader": "Tagged Image Batch Loader",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
