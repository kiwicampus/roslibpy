from base64 import standard_b64decode
from io import BytesIO

from PIL import Image


def decode_png(string: str):
    """b64 decode the string, then PNG-decompress"""
    decoded = standard_b64decode(string)
    buff = BytesIO(decoded)
    i = Image.open(buff)
    return i.tobytes().decode("utf-8")
