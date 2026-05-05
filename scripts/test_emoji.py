from PIL import Image, ImageDraw, ImageFont

# --- CONFIG ---
IMG_PATH = "image_1.png"
OUT_PATH = "image_output.png"

TEXT = "🔥 Big Sale Today!\n📱 iPhone Deals\n🚚 Fast Delivery"

# Try to point this to a real emoji font on your system
EMOJI_FONT_PATH = "/System/Library/Fonts/Apple Color Emoji.ttc"  # Mac
# Linux alternative:
# EMOJI_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

TEXT_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"

# --- LOAD IMAGE ---
img = Image.open(IMG_PATH).convert("RGBA")
draw = ImageDraw.Draw(img)

W, H = img.size

# --- FONTS ---
text_font = ImageFont.truetype(TEXT_FONT_PATH, 60)
emoji_font = ImageFont.truetype(EMOJI_FONT_PATH, 60)

# --- DRAW DARK OVERLAY (for story style) ---
overlay = Image.new("RGBA", img.size, (0, 0, 0, 120))
img = Image.alpha_composite(img, overlay)
draw = ImageDraw.Draw(img)

# --- SIMPLE EMOJI DETECTION ---
def is_emoji(char):
    return ord(char) > 10000  # crude but works well enough

# --- DRAW TEXT WITH EMOJIS ---
def draw_text_with_emojis(draw, text, x, y):
    for line in text.split("\n"):
        cx = x
        for ch in line:
            font = emoji_font if is_emoji(ch) else text_font

            # shadow
            draw.text((cx+2, y+2), ch, font=font, fill=(0,0,0,180))

            # main text
            draw.text((cx, y), ch, font=font, fill=(255,255,255,255))

            # advance cursor
            cx += draw.textlength(ch, font=font)

        y += 80  # line spacing

# --- CENTER TEXT ---
text_x = 80
text_y = H // 2 - 100

draw_text_with_emojis(draw, TEXT, text_x, text_y)

# --- SAVE ---
img.convert("RGB").save(OUT_PATH)
print("Saved:", OUT_PATH)