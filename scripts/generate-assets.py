from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
assets = root / "assets"
assets.mkdir(exist_ok=True)
image = Image.new("RGBA", (512, 512), "#071013")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((22, 22, 490, 490), radius=86, fill="#071013", outline="#18383e", width=6)
draw.polygon([(86, 76), (344, 76), (426, 158), (426, 432), (168, 432), (86, 350)], fill="#0d1a1e", outline="#59e2d2", width=14)
draw.line((344, 76, 344, 158, 426, 158), fill="#59e2d2", width=14)
try:
    font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 102)
except OSError:
    font = ImageFont.load_default()
draw.text((145, 186), "MB", fill="#59e2d2", font=font)
draw.line((154, 330, 356, 330), fill="#f3b861", width=18)
draw.line((186, 378, 324, 378), fill="#f3b861", width=18)
png = assets / "mobile-base-imager.png"
ico = assets / "mobile-base-imager.ico"
image.save(png)
image.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(png)
print(ico)
