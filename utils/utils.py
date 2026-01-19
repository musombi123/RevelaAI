from PIL import Image


# -------- IMAGE UTILITIES --------
def simple_process(image: Image.Image, scale: float) -> Image.Image:
    """
    Simple image resize utility.
    """
    if scale != 1.0:
        w, h = image.size
        image = image.resize((int(w * scale), int(h * scale)))
    return image


# -------- TEXT UTILITIES --------
def preprocess(text: str) -> str:
    """
    Simple placeholder text preprocessing.
    """
    return text.strip().lower()


def postprocess(output) -> str:
    """
    Simple placeholder postprocessing.
    """
    return str(output)
