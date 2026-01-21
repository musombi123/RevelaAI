from cog import BasePredictor, Input, Path
from PIL import Image
from utils import simple_process


class Predictor(BasePredictor):
    def setup(self):
        """
        Load resources into memory.
        No ML model yet.
        """
        self.model = None

    def predict(
        self,
        image: Path = Input(description="Input image"),
        scale: float = Input(description="Scale factor", default=1.0),
    ) -> Path:
        """
        Dummy image processing.
        """
        img = Image.open(image)
        output_img = simple_process(img, scale)

        output_path = Path("output.png")
        output_img.save(output_path)

        return output_path
