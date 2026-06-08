from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "CryptoStream_AI_Architecture_Flowchart.png"

W, H = 1920, 1080
BG = (8, 18, 38)
CARD = (18, 42, 72)
CARD2 = (22, 52, 86)
WHITE = (245, 248, 252)
MUTED = (170, 185, 205)
CYAN = (38, 198, 218)
BLUE = (66, 133, 244)
PURPLE = (126, 87, 194)
AMBER = (255, 193, 7)
GREEN = (76, 175, 80)
RED = (239, 83, 80)
LINE = (86, 122, 160)


def font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\LeelawUI.ttf",
        r"C:\Windows\Fonts\LeelUIsl.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    bold_candidates = [
        r"C:\Windows\Fonts\LeelaUIb.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ]
    for path in (bold_candidates if bold else candidates):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


F_TITLE = font(58, True)
F_SUB = font(27)
F_HEAD = font(31, True)
F_BODY = font(23)
F_SMALL = font(20)
F_TINY = font(17)


def rounded(draw, xy, r, fill, outline=None, width=2):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def text_center(draw, xy, text, fnt, fill=WHITE, spacing=6):
    x1, y1, x2, y2 = xy
    lines = text.split("\n")
    heights = []
    widths = []
    for line in lines:
        box = draw.textbbox((0, 0), line, font=fnt)
        widths.append(box[2] - box[0])
        heights.append(box[3] - box[1])
    total_h = sum(heights) + spacing * (len(lines) - 1)
    y = y1 + (y2 - y1 - total_h) / 2
    for line, w, h in zip(lines, widths, heights):
        draw.text((x1 + (x2 - x1 - w) / 2, y), line, font=fnt, fill=fill)
        y += h + spacing


def text_left(draw, x, y, text, fnt, fill=WHITE, spacing=8):
    for line in text.split("\n"):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += fnt.size + spacing


def arrow(draw, start, end, color=CYAN, width=5):
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    if x2 >= x1:
        pts = [(x2, y2), (x2 - 22, y2 - 13), (x2 - 22, y2 + 13)]
    else:
        pts = [(x2, y2), (x2 + 22, y2 - 13), (x2 + 22, y2 + 13)]
    draw.polygon(pts, fill=color)


def card(draw, xy, accent, title, body):
    x1, y1, x2, y2 = xy
    rounded(draw, xy, 26, CARD, (50, 82, 118), 2)
    rounded(draw, (x1, y1, x1 + 18, y2), 10, accent)
    draw.text((x1 + 38, y1 + 28), title, font=F_HEAD, fill=WHITE)
    text_left(draw, x1 + 38, y1 + 82, body, F_BODY, MUTED, spacing=6)


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# subtle grid
for x in range(0, W, 80):
    d.line([(x, 0), (x, H)], fill=(11, 27, 51), width=1)
for y in range(0, H, 80):
    d.line([(0, y), (W, y)], fill=(11, 27, 51), width=1)

d.text((95, 68), "CryptoStream AI", font=F_TITLE, fill=WHITE)
d.text((98, 137), "Real-time Market Intelligence Flowchart", font=F_SUB, fill=CYAN)
d.text((98, 178), "From noisy market data to actionable intelligence, risk guardrails, alerts and operator workflow", font=F_TINY, fill=MUTED)

# Main cards
cards = [
    ((85, 290, 390, 485), CYAN, "1. Data Sources", "Binance / Yahoo Finance\nFRED macro indicators\nMT5 broker context"),
    ((455, 290, 760, 485), BLUE, "2. Ingestion", "Kafka streaming events\nAirflow batch jobs\nAPI connectors"),
    ((825, 290, 1130, 485), PURPLE, "3. Processing", "Flink stream processing\nPython intelligence service\ndbt transformation"),
    ((1195, 290, 1500, 485), GREEN, "4. Storage", "PostgreSQL / SQLite\npgvector knowledge store\nParquet Data Lake / Redis"),
]

for c in cards:
    card(d, *c)

for x in [390, 760, 1130]:
    arrow(d, (x + 18, 388), (x + 62, 388), CYAN, 5)

# Intelligence layer
rounded(d, (280, 615, 1640, 830), 34, (13, 35, 63), (55, 88, 124), 2)
d.text((330, 645), "5. AI Intelligence & Risk Guardrails", font=F_HEAD, fill=WHITE)
d.text((332, 690), "Market signal scoring, anomaly detection, RAG context retrieval, confidence score and freshness checks", font=F_SMALL, fill=MUTED)

sub = [
    ((335, 735, 585, 790), PURPLE, "Signal Scoring"),
    ((630, 735, 880, 790), RED, "Anomaly Detection"),
    ((925, 735, 1175, 790), BLUE, "RAG Context"),
    ((1220, 735, 1470, 790), AMBER, "Risk Guardrails"),
]
for xy, accent, label in sub:
    rounded(d, xy, 18, CARD2, accent, 3)
    text_center(d, xy, label, F_SMALL, WHITE)

arrow(d, (1348, 485), (1348, 615), GREEN, 5)

# Output cards
outputs = [
    ((255, 910, 555, 1010), GREEN, "Dashboard", "React dashboard / AI chat"),
    ((655, 910, 955, 1010), AMBER, "Alerts", "Telegram + monitoring channel"),
    ((1055, 910, 1355, 1010), CYAN, "Decision Support", "review / monitor / escalate"),
]
for xy, accent, h, b in outputs:
    rounded(d, xy, 24, CARD, (50, 82, 118), 2)
    rounded(d, (xy[0], xy[1], xy[0] + 16, xy[3]), 8, accent)
    d.text((xy[0] + 36, xy[1] + 20), h, font=F_HEAD, fill=WHITE)
    d.text((xy[0] + 36, xy[1] + 62), b, font=F_TINY, fill=MUTED)

for x in [405, 805, 1205]:
    arrow(d, (960, 830), (x, 910), CYAN, 4)

# Key message
rounded(d, (1500, 860, 1815, 1025), 26, (13, 35, 63), (55, 88, 124), 2)
d.text((1530, 887), "Outcome", font=F_HEAD, fill=WHITE)
text_left(d, 1530, 934, "Faster analysis\nSafer decision making\nOperational visibility", F_TINY, MUTED, spacing=2)
arrow(d, (1355, 960), (1500, 960), GREEN, 4)

img.save(OUT)
print(OUT)
