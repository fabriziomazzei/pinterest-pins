"""Build vertical Pinterest pins (1000x1500 PNG) from Etsy listing images.

Usage: python3 tools/build_pins.py spec.json
spec.json = {"key": "kit", "images_dir": "/mnt/project-files/kit-colloquio/immagini-inserzione",
             "pins": [{"img": "01", "eyebrow": "JOB SEARCH KIT", "headline": "...", "top": 150}, ...]}
img 01 = 3D cover (crop from y=150); other images: "top" = y where the content starts
below the image's own title (look at the image and set it, typically 540-760).
Output: pin/pin-<key>-<n>.png (n = position in the list, from 1).
"""
import json, sys, os
from PIL import Image, ImageDraw, ImageFont
F = '/usr/share/fonts/opentype/inter/'
H = ImageFont.truetype(F + 'InterDisplay-Bold.otf', 74)
E = ImageFont.truetype(F + 'Inter-Bold.otf', 26)
P = ImageFont.truetype(F + 'Inter-Bold.otf', 30)
S = ImageFont.truetype(F + 'Inter-Medium.otf', 26)
BG, G, INK = '#FAF8F5', '#0A7A3B', '#1E2A23'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pin')

def wrap(d, t, f, w):
    out, cur = [], ''
    for word in t.split():
        x = (cur + ' ' + word).strip()
        if d.textlength(x, font=f) <= w: cur = x
        else: out.append(cur); cur = word
    out.append(cur); return out

def build(spec):
    for n, p in enumerate(spec['pins'], 1):
        c = Image.new('RGB', (1000, 1500), BG); d = ImageDraw.Draw(c)
        y = 80
        d.text((500, y), p['eyebrow'], font=E, fill=G, anchor='mt'); y += 56
        for ln in wrap(d, p['headline'], H, 860):
            d.text((500, y), ln, font=H, fill=INK, anchor='mt'); y += 86
        src = Image.open(os.path.join(spec['images_dir'], p['img'] + '.png')).convert('RGB')
        crop = src.crop((600, p.get('top', 150), 2400, 2150)) if p['img'] == '01' else src.crop((620, p.get('top', 600), 2380, 2150))
        top, bottom = y + 20, 1500 - 210
        h = bottom - top; w = int(crop.width * h / crop.height)
        if w > 940: w = 940; h = int(crop.height * w / crop.width)
        crop = crop.resize((w, h), Image.LANCZOS)
        c.paste(crop, ((1000 - w) // 2, top + (bottom - top - h) // 2))
        pill = 'MAKE AI WORK FOR YOU'; pw = d.textlength(pill, font=P) + 70
        d.rounded_rectangle(((1000 - pw) / 2, 1330, (1000 + pw) / 2, 1390), radius=30, fill=G)
        d.text((500, 1360), pill, font=P, fill='white', anchor='mm')
        d.text((500, 1438), 'Fabrizio Mazzei  ·  Instant digital download', font=S, fill='#5B6660', anchor='mm')
        out = os.path.join(OUT, f"pin-{spec['key']}-{n}.png")
        c.save(out, optimize=True); print(out)

if __name__ == '__main__':
    build(json.load(open(sys.argv[1])))
