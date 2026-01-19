from cog import BasePredictor, Input, Path
from PIL import Image
import torch
from utils import simple_process


class Predictor(BasePredictor):
    def setup(self):
        """
        Load model into memory.
        If you don't have a trained model yet, this is a placeholder.
        """
        self.model = None  # replace later with torch.load("model.pth")

    def predict(
        self,
        image: Path = Input(description="Input image"),
        scale: float = Input(description="Scale factor", default=1.0),
    ) -> Path:
        """
        Run a dummy prediction (image passthrough).
        Replace this with real inference later.
        """
        img = Image.open(image)
        output_img = simple_process(img, scale)

        output_path = Path("output.png")
        output_img.save(output_path)

        return output_path
