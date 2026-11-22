from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = 512
image = Image.new("RGBA", (SIZE, SIZE), (7, 12, 22, 255))
draw = ImageDraw.Draw(image)

# Draw the same rounded dark tile, three candlesticks, and rising cyan arrow as logo.svg.
draw.rounded_rectangle((16, 16, 496, 496), radius=120,
                       fill=(16, 24, 39, 255), outline=(51, 65, 85, 255), width=8)
draw.line((108, 364, 404, 364), fill=(51, 65, 85, 255), width=14)

bars = ((144, 224, 194, 314), (244, 156, 294, 314), (344, 204, 394, 314))
for x0, top, x1, bottom in bars:
    color = (34, 211, 238, 255) if top < 200 else (129, 140, 248, 255)
    draw.line((x0 + 25, top - 52, x0 + 25, top), fill=color, width=16)
    draw.rounded_rectangle((x0, top, x1, bottom), radius=8,
                           outline=color, width=18)
    draw.line((x0 + 25, bottom, x0 + 25, bottom + 50), fill=color, width=16)

points = ((112, 184), (210, 148), (286, 176), (400, 90))
for start, end in zip(points, points[1:]):
    for offset in range(0, 100, 4):
        x = start[0] + (end[0] - start[0]) * offset / 100
        y = start[1] + (end[1] - start[1]) * offset / 100
        color = (34 + offset, 211 - offset // 2, 238, 255)
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)
draw.line(points, fill=(53, 201, 239, 255), width=16, joint="curve")
draw.line((400, 90, 390, 146), fill=(53, 201, 239, 255), width=15)
draw.line((400, 90, 344, 100), fill=(53, 201, 239, 255), width=15)

image.save(ROOT / "assets" / "app.ico", format="ICO",
           sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
