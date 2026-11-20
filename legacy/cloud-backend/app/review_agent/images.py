"""CLI/reference adapter: read one verified embedded picture from a local PPTX."""
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .models import ReviewError


class LocalPptxImages:
    def __init__(self, path):
        self.path = Path(path)
        self._deck = None

    def __call__(self, image):
        if self.path.suffix.lower() != ".pptx":
            raise ReviewError("image_unavailable", "原文件不是 PPTX。")
        if self._deck is None:
            self._deck = Presentation(self.path)
        if image.source.slide is None or not 1 <= image.source.slide <= len(self._deck.slides):
            raise ReviewError("image_unavailable", "找不到该幻灯片。")
        slide = self._deck.slides[image.source.slide - 1]
        if str(slide.part.partname).lstrip("/") != image.source.part:
            raise ReviewError("image_unavailable", "无法核对幻灯片的内部位置。")
        def walk(shapes):
            for shape in shapes:
                yield shape
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    yield from walk(shape.shapes)
        identifier = image.source.path.rsplit("/shape/", 1)[-1]
        item = next((shape for shape in walk(slide.shapes) if str(shape.shape_id) == identifier), None)
        if item is None:
            raise ReviewError("image_unavailable", "找不到要分析的嵌入图片。")
        # The runner verifies MIME, length and SHA-256 against the confirmed B structure.
        return item.image.blob
