from PIL import Image, ImageDraw, ImageFont
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class VisualMarkupEngine:
    """
    Overlays institutional trading zones (ICT/SMC) onto chart images.
    Transforms raw charts into 'Institutional Proofs'.
    """
    def __init__(self):
        self.colors = {
            "order_block": (0, 150, 255, 60),    # Blue translucent
            "fvg": (255, 100, 0, 40),          # Orange translucent
            "whale_wall": (255, 0, 50, 80),    # Red solid-ish
            "text": (255, 255, 255, 255)       # White
        }

    def apply_markup(self, image_path: str, zones: List[Dict[str, Any]]) -> str:
        """
        Draws boxes on the image. 
        'zones' expects list of {type: 'ob', box: [x1, y1, x2, y2], label: 'Bullish OB'}
        """
        if not os.path.exists(image_path):
            return image_path

        try:
            with Image.open(image_path).convert("RGBA") as base:
                # Create a transparent layer for boxes
                overlay = Image.new("RGBA", base.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(overlay)
                
                for zone in zones:
                    z_type = zone.get("type", "order_block")
                    box = zone.get("box", [50, 50, 200, 200]) # Dummy coords
                    color = self.colors.get(z_type, (255, 255, 255, 100))
                    
                    # Draw the rectangle
                    draw.rectangle(box, fill=color, outline=(255,255,255, 150))
                    
                    # Label
                    label = zone.get("label", "")
                    if label:
                        draw.text((box[0], box[1]-15), label, fill=(255,255,255, 255))

                # Composite the layers
                out = Image.alpha_composite(base, overlay)
                
                # Save as a new file to avoid overwriting original evidence
                marked_path = image_path.replace(".png", "_marked.png")
                out.convert("RGB").save(marked_path, "PNG")
                
                logger.info(f"VisualMarkup: Marked chart saved to {marked_path}")
                return marked_path
        except Exception as e:
            logger.error(f"VisualMarkup: Failed to apply markup: {e}")
            return image_path

visual_markup = VisualMarkupEngine()
