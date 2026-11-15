import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps, PngImagePlugin

PngImagePlugin.MAX_TEXT_CHUNK = 100 * 1024 * 1024
logger = logging.getLogger(__name__)


IMAGE_PROFILES: dict[str, dict[str, Any]] = {
    "icon": {"format": "PNG", "aspect": 1.0, "size": (256, 256), "convert_rgba": True},
    "logo": {
        "format": "PNG",
        "trim": True,
        "max_dim": (800, None),
        "size_mb": 0.8,
        "convert_rgba": True,
    },
    "hero": {"format": "JPEG", "aspect": 96 / 31, "size": (3840, 1240), "size_mb": 1.2},
    "background": {
        "format": "JPEG",
        "aspect": 16 / 9,
        "size": (3840, 2160),
        "size_mb": 1.8,
    },
    "screenshot": {
        "format": "JPEG",
        "max_dim": (1920, 1080),
        "size_mb": 1.0,
        "prefix": True,
    },
    "box": {"format": "JPEG", "max_dim": (1920, 1080), "size_mb": 1.0, "prefix": True},
    "cart": {"format": "JPEG", "max_dim": (1920, 1080), "size_mb": 1.0, "prefix": True},
    "advertisement": {
        "format": "JPEG",
        "max_dim": (1920, 1080),
        "size_mb": 1.0,
        "prefix": True,
    },
    "disc": {"format": "JPEG", "max_dim": (1920, 1080), "size_mb": 1.0},
    "cover": {"custom": "_process_cover"},
}


class ImageProcessor:
    """Resizes and optimizes images."""

    def process_image(
        self,
        image_type: str,
        source_path: Path | str,
        destination_dir: Path | str,
        target_name: str | None = None,
    ) -> str | None:
        """
        Process an image according to its type profile.
        Args:
            image_type: The image profile type (e.g., 'box', 'screenshot').
            source_path: The path to the source image.
            destination_dir: The directory to save the processed image.
            target_name: The target basename. Defaults to source stem.
        Returns:
            The path to the processed image, or None if failed.
        """
        src_p = Path(source_path)
        if not src_p.exists():
            logger.warning(f"Source file not found: {source_path}. Skipping.")
            return None

        destination_basename = target_name or src_p.stem

        # Determine base type to ignore trailing index suffix (e.g., "cover-02" -> "cover")
        base_type = image_type
        if "-" in image_type:
            parts = image_type.rsplit("-", 1)
            if parts[1].isdigit():
                base_type = parts[0]

        profile = self._resolve_profile(base_type)
        if not profile:
            logger.warning(f"Unknown image type '{image_type}' (base: '{base_type}'). Skipping processing.")
            return None

        # Determine output format and extension
        fmt = profile.get("format", "JPEG")
        ext = ".png" if fmt.upper() == "PNG" else ".jpg"
        destination_path = str(Path(destination_dir) / (destination_basename + ext))

        try:
            with Image.open(src_p) as img:
                if "custom" in profile:
                    custom_method = getattr(self, profile["custom"])
                    output_path = custom_method(img, destination_path)
                else:
                    output_path = self._apply_profile(img, profile, destination_path)
        except Exception as e:
            logger.error(f"Failed to process '{source_path}': {e}")
            return None

        return output_path

    def _resolve_profile(self, base_type: str) -> dict[str, Any] | None:
        # Exact match
        if base_type in IMAGE_PROFILES:
            return IMAGE_PROFILES[base_type]
        # Prefix match
        for key, config in IMAGE_PROFILES.items():
            if config.get("prefix") and base_type.startswith(key):
                return config
        return None

    def _apply_profile(self, img: Image.Image, profile: dict[str, Any], destination_path: str) -> str:
        if profile.get("convert_rgba") and "A" not in img.getbands():
            img = img.convert("RGBA")

        if profile.get("trim"):
            img = self._trim_transparent_border(img)

        if "aspect" in profile:
            img = self._enforce_aspect(img, target_aspect=profile["aspect"])

        if "size" in profile:
            target_w, target_h = profile["size"]
            img = self._resize_to_target_dimensions(img, target_w, target_h)

        if "max_dim" in profile:
            max_w, max_h = profile["max_dim"]
            img = self._resize_to_max_dimension(img, max_width=max_w, max_height=max_h)

        fmt = profile.get("format", "JPEG")
        size_mb = profile.get("size_mb")

        if size_mb:
            return self._optimize_and_save_image(img, destination_path, target_size_mb=size_mb, output_format=fmt)
        else:
            return self._save_image(img, destination_path, output_format=fmt)

    def _process_cover(self, img: Image.Image, destination_path: str) -> str:
        orig_w, orig_h = img.size
        orig_aspect = orig_w / orig_h

        img = self._detect_and_crop_borders(img)
        img_aspect = img.width / img.height
        aspect_2_3 = 2 / 3
        aspect_3_4 = 3 / 4

        diff_2_3 = abs(orig_aspect - aspect_2_3)
        diff_3_4 = abs(orig_aspect - aspect_3_4)

        if diff_2_3 <= diff_3_4:
            target_aspect = aspect_2_3
            target_w, target_h = 600, 900
        else:
            target_aspect = aspect_3_4
            target_w, target_h = 600, 800

        rel_diff = max(img_aspect / target_aspect, target_aspect / img_aspect) - 1.0

        # Select scaling filter based on whether the image is low-res/pixel-art
        resample_filter = Image.Resampling.LANCZOS
        if img.width < 500 or img.height < 500:
            resample_filter = Image.Resampling.NEAREST

        if rel_diff > 0.15:
            # Aspect ratio mismatch: Fit inside with blurred background
            img = self._create_padded_blurred_image(img, target_w, target_h, resample_filter)
        else:
            # Aspect ratios match closely: Crop and resize
            img = self._enforce_aspect(img, target_aspect=target_aspect)
            img = img.resize((target_w, target_h), resample_filter)

        return self._optimize_and_save_image(img, destination_path, target_size_mb=0.6, output_format="JPEG")

    def _create_padded_blurred_image(
        self,
        img: Image.Image,
        target_w: int,
        target_h: int,
        resample_filter: Image.Resampling = Image.Resampling.LANCZOS,
    ) -> Image.Image:
        img_rgb = img.convert("RGB")
        target_size = (target_w, target_h)

        # Background: Scale and crop to fill the target size, then blur & darken
        bg_img = ImageOps.fit(img_rgb, target_size, method=Image.Resampling.LANCZOS)
        bg_blurred = bg_img.filter(ImageFilter.GaussianBlur(radius=15))
        bg_dark = Image.eval(bg_blurred, lambda x: int(x * 0.4))

        # Foreground: Scale to fit inside the target size
        inner_img = ImageOps.contain(img_rgb, target_size, method=resample_filter)

        # Paste foreground centered on top of the blurred background
        x_offset = (target_w - inner_img.width) // 2
        y_offset = (target_h - inner_img.height) // 2
        bg_dark.paste(inner_img, (x_offset, y_offset))

        return bg_dark

    def _detect_and_crop_borders(self, img: Image.Image, tolerance: int = 15) -> Image.Image:
        img_rgb = img.convert("RGB")
        w, h = img.size

        # Get colors of the 4 corners to guess the background color
        corners = [
            img_rgb.getpixel((0, 0)),
            img_rgb.getpixel((w - 1, 0)),
            img_rgb.getpixel((0, h - 1)),
            img_rgb.getpixel((w - 1, h - 1)),
        ]

        # Use the most common corner color as the background candidate
        bg_color = Counter(corners).most_common(1)[0][0]

        # Create a background template image of the same size
        bg_img = Image.new("RGB", img.size, bg_color)

        # Find difference between image and background template
        diff = ImageChops.difference(img_rgb, bg_img)
        diff_gray = diff.convert("L")
        thresholded = diff_gray.point(lambda p: 255 if p > tolerance else 0)

        bbox = thresholded.getbbox()
        if bbox:
            left, top, right, bottom = bbox
            content_w = right - left
            content_h = bottom - top
            content_area = content_w * content_h
            total_area = w * h

            # If content area is less than 88% of total area, we crop it
            content_ratio = content_area / total_area
            if content_ratio < 0.88:
                logger.info(
                    f"Significant blank space detected ({content_ratio:.1%} content area). "
                    f"Cropping cover to content bounding box {bbox}."
                )
                return img.crop(bbox)

        return img

    def _enforce_aspect(self, img: Image.Image, target_aspect: float) -> Image.Image:
        img_aspect = img.width / img.height
        if abs(img_aspect - target_aspect) < 0.01:
            return img

        if img_aspect > target_aspect:
            target_height = img.height
            target_width = int(target_height * target_aspect)
        else:
            target_width = img.width
            target_height = int(target_width / target_aspect)

        left = (img.width - target_width) // 2
        top = (img.height - target_height) // 2
        right = left + target_width
        bottom = top + target_height

        return img.crop((left, top, right, bottom))

    def _resize_to_target_dimensions(self, img: Image.Image, target_width: int, target_height: int) -> Image.Image:
        if img.width == target_width and img.height == target_height:
            return img
        return img.resize((target_width, target_height), Image.Resampling.LANCZOS)

    def _resize_to_max_dimension(
        self, img: Image.Image, max_width: int | None = None, max_height: int | None = None
    ) -> Image.Image:
        current_width = img.width
        current_height = img.height

        if (max_width is None and max_height is None) or (
            (max_width is None or current_width <= max_width) and (max_height is None or current_height <= max_height)
        ):
            return img

        scale_factors = []
        if max_width is not None and current_width > max_width:
            scale_factors.append(max_width / current_width)

        if max_height is not None and current_height > max_height:
            scale_factors.append(max_height / current_height)

        scale = min(scale_factors) if scale_factors else 1.0
        return img.resize(
            (int(current_width * scale), int(current_height * scale)),
            Image.Resampling.LANCZOS,
        )

    def _trim_transparent_border(self, img: Image.Image) -> Image.Image:
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        return img

    def _save_image(self, img: Image.Image, destination_path: str, output_format: str = "JPEG") -> str:
        p_out = Path(destination_path)
        p_out.parent.mkdir(parents=True, exist_ok=True)
        p_temp = p_out.with_name(f".{p_out.name}.tmp")
        try:
            img.save(p_temp, format=output_format)
            os.replace(p_temp, p_out)
        except Exception:
            p_temp.unlink(missing_ok=True)
            raise
        return str(p_out)

    def _optimize_and_save_image(
        self,
        img: Image.Image,
        destination_path: str,
        target_size_mb: float = 2.0,
        output_format: str = "JPEG",
    ) -> str:
        p_out = Path(destination_path)
        p_out.parent.mkdir(parents=True, exist_ok=True)

        if output_format.upper() in ["JPEG", "JPG"] and img.mode != "RGB":
            img = img.convert("RGB")

        p_temp = p_out.with_name(f".{p_out.name}.tmp")
        saved_ok = False

        quality = 95
        while quality >= 10:
            try:
                img.save(p_temp, format=output_format, quality=quality)
                saved_ok = True
                if p_temp.stat().st_size / (1024 * 1024) <= target_size_mb:
                    break
            except Exception as e:
                logger.error(f"Error saving temp quality {quality}: {e}")
                break
            quality -= 5

        try:
            if not saved_ok or not p_temp.exists():
                raise OSError(f"Failed to save optimized image to temporary path {p_temp}")
            os.replace(p_temp, p_out)
        except Exception as e:
            logger.error(f"Error replacing output image {p_out}: {e}")
            p_temp.unlink(missing_ok=True)
            raise

        return str(p_out)
