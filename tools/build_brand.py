"""Generate Tuesly's original geometric mark and light/dark HA brand images."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "tuesly" / "brand"
ASSETS = ROOT / "assets"
NAVY = "#111D35"
BLUE = "#6478FF"
CYAN = "#49D9EC"


def mark(size):
    image = Image.new("RGBA", (512, 512))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 488, 488), radius=116, fill=NAVY)
    draw.line([(112, 112), (160, 176), (256, 176), (400, 112)], fill=CYAN, width=12, joint="curve")
    draw.line([(256, 312), (256, 350), (126, 398)], fill=CYAN, width=12, joint="curve")
    draw.line([(256, 350), (386, 398)], fill=CYAN, width=12, joint="curve")
    for x, y in ((112, 112), (400, 112), (126, 398), (386, 398)):
        draw.ellipse((x-19, y-19, x+19, y+19), fill=CYAN)
        draw.ellipse((x-7, y-7, x+7, y+7), fill=NAVY)
    draw.rounded_rectangle((152, 153, 360, 221), radius=19, fill=BLUE)
    draw.rounded_rectangle((221, 194, 291, 348), radius=18, fill=BLUE)
    draw.rounded_rectangle((160, 160, 350, 168), radius=4, fill="#9BA8FF")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def font(size, bold=False):
    candidates = [Path("C:/Windows/Fonts") / ("segoeuib.ttf" if bold else "segoeui.ttf"),
                  Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("Install Segoe UI or DejaVu Sans to render the wordmark")


def logo(width, dark=False):
    image = Image.new("RGBA", (1024, 320))
    image.alpha_composite(mark(264), (16, 28))
    draw = ImageDraw.Draw(image)
    draw.text((320, 32), "Tuesly", font=font(114, True), fill="#EDF2FF" if dark else NAVY)
    draw.text((326, 185), "ARCHITECH LABS", font=font(29), fill="#A9B8D7" if dark else "#50627D")
    return image.resize((width, round(width*320/1024)), Image.Resampling.LANCZOS)


def main():
    BRAND.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    for size, suffix in ((256, ""), (512, "@2x")):
        mark(size).save(BRAND / f"icon{suffix}.png")
        mark(size).save(BRAND / f"dark_icon{suffix}.png")
    for width, suffix in ((512, ""), (1024, "@2x")):
        logo(width).save(BRAND / f"logo{suffix}.png")
        logo(width, True).save(BRAND / f"dark_logo{suffix}.png")
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect x="24" y="24" width="464" height="464" rx="116" fill="#111D35"/>
<g stroke="#49D9EC" stroke-width="12" stroke-linejoin="round" fill="none">
<path d="M112 112L160 176H256L400 112M256 312V350L126 398M256 350L386 398"/></g>
<g fill="#49D9EC"><circle cx="112" cy="112" r="19"/><circle cx="400" cy="112" r="19"/><circle cx="126" cy="398" r="19"/><circle cx="386" cy="398" r="19"/></g>
<g fill="#111D35"><circle cx="112" cy="112" r="7"/><circle cx="400" cy="112" r="7"/><circle cx="126" cy="398" r="7"/><circle cx="386" cy="398" r="7"/></g>
<g fill="#6478FF"><rect x="152" y="153" width="208" height="68" rx="19"/><rect x="221" y="194" width="70" height="154" rx="18"/></g>
<rect x="160" y="160" width="190" height="8" rx="4" fill="#9BA8FF"/>
</svg>'''
    (ASSETS / "tuesly-icon.svg").write_text(svg + "\n", encoding="utf-8")
    preview = Image.new("RGBA", (1100, 760), "#F2F5FC")
    preview.alpha_composite(logo(900), (90, 40))
    dark = Image.new("RGBA", (1100, 380), "#090F1E")
    dark.alpha_composite(logo(900, True), (90, 40))
    preview.alpha_composite(dark, (0, 380))
    preview.convert("RGB").save(ASSETS / "brand-preview.png")
    print("Generated 8 local HA brand images, SVG mark, and preview")


if __name__ == "__main__":
    main()
