from PIL import Image, ImageDraw, ImageFont
import textwrap
import logging

logger = logging.getLogger(__name__)


def create_og_image(
    text: str, font: str, size: tuple[int, int], logo_image: str, font_size: int = 64
) -> Image.Image:
    """
    Create an OG image with text and logo.

    Args:
        text: Text to display on the image
        font: Path to font file or font name
        size: Tuple of (width, height) for the image
        logo_image: Path to logo image file
        font_size: Font size in pixels (default: 64)

    Returns:
        PIL Image object
    """
    # Create base image with white background
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)

    # Calculate dimensions
    width, height = size
    text_area_width = int(width * 1)  # Text takes 70% of width
    logger.info(f"text_area_width={text_area_width}")
    logo_area_width = width - text_area_width

    # Load and resize logo
    try:
        logo = Image.open(logo_image)
        # Resize logo to 10% of image width
        logo_size = int(width * 0.21)
        logo_max_size = (logo_size, logo_size)
        logo.thumbnail(logo_max_size, Image.Resampling.LANCZOS)

        # Position logo in bottom right corner with 80px padding
        logo_x = width - logo.width - 20
        logo_y = height - logo.height - 40
        img.paste(logo, (logo_x, logo_y), logo if logo.mode == "RGBA" else None)
    except Exception as e:
        print(f"Warning: Could not load logo image: {e}")

    # Load font
    try:
        if font.endswith((".ttf", ".otf")):
            # Font file path provided
            font_obj = ImageFont.truetype(font, size=font_size)
        elif font == "inter" or font == "default":
            # Use Inter font as default (bold version)
            font_obj = ImageFont.truetype(
                "static/fonts/Inter-SemiBold.ttf", size=font_size
            )
        else:
            # Try to load as system font with configurable size
            font_obj = ImageFont.load_default(size=font_size)
    except Exception as e:

        logger.warning(f"Failed to load the font, using the default one {str(e)}")
        # Fallback to default font with configurable size
        font_obj = ImageFont.load_default(size=font_size)

    # Wrap text to fit in the text area
    # Calculate actual character width based on font size and available space
    test_text = "A" * 10  # Sample text to measure average character width
    test_bbox = draw.textbbox((0, 0), test_text, font=font_obj)
    avg_char_width = (test_bbox[2] - test_bbox[0]) / len(test_text)
    logger.info(f"avg_char_width={avg_char_width}")
    # Account for padding (40px on left, some space from logo area)
    available_width = text_area_width  # 40px left padding + 40px right margin
    chars_per_line = int(available_width // avg_char_width)

    # Ensure we have at least some characters per line
    logger.info(f"chars_per_line={chars_per_line}")
    chars_per_line = max(chars_per_line, 10)

    # Handle explicit newlines by processing each line separately
    lines = text.split('\n')
    wrapped_lines = []
    for line in lines:
        if line.strip():  # Only wrap non-empty lines
            wrapped_lines.append(textwrap.fill(line, width=chars_per_line))
        else:
            wrapped_lines.append('')  # Preserve empty lines
    wrapped_text = '\n'.join(wrapped_lines)

    # Calculate text position (positioned closer to top)
    text_bbox = draw.textbbox((0, 0), wrapped_text, font=font_obj)
    text_height = text_bbox[3] - text_bbox[1]
    text_x = 40  # 20px padding from left
    text_y = int(height * 0.25)  # Position at 25% from top instead of center
    logger.info(f"height={height} text_height={text_height}")
    # Draw text with increased line spacing
    line_spacing = font_size * 0.6  # 30% of font size for line spacing
    draw.text(
        (text_x, text_y),
        wrapped_text,
        fill="black",
        font=font_obj,
        spacing=line_spacing,
    )
    logger.info(f"text_x = {text_x} text_y={text_y}")
    return img


def save_og_image(
    text: str,
    font: str,
    size: tuple[int, int],
    logo_image: str,
    output_path: str,
    font_size: int = 64,
):
    """
    Create and save an OG image.

    Args:
        text: Text to display on the image
        font: Path to font file or font name
        size: Tuple of (width, height) for the image
        logo_image: Path to logo image file
        output_path: Path where to save the generated image
        font_size: Font size in pixels (default: 64)
    """
    img = create_og_image(text, font, size, logo_image, font_size)
    img.save(output_path, "PNG", optimize=True)
