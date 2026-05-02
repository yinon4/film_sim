#!/usr/bin/env python3
"""
film_simulator.py

JPEG/PNG/TIFF-friendly photographic film simulator.

This version is tuned for already-processed digital images. It keeps the source
image mostly intact by default, then adds a controllable film process:

1. RGB scene light is converted to red/green/blue-sensitive emulsion-layer exposure.
2. Silver-halide crystals receive stochastic exposure.
3. A latent image forms.
4. Development creates metallic silver density.
5. Color developer forms cyan/magenta/yellow dye clouds.
6. Bleach/fix removes silver, leaving dye density.
7. The negative is scanned back to a positive image.
8. The scanned result is blended with the original JPEG to keep a neutral look.

Install:
    pip install numpy pillow

Example:
    python film_simulator.py input.jpg output.jpg
    python film_simulator.py input.jpg output.jpg --effect-strength 0.45 --grain 0.45
    python film_simulator.py input.jpg negative.png --output-stage negative

The defaults are intentionally subtle. For more visible grain, raise --grain.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

Array = np.ndarray
OutputStage = Literal["positive", "negative", "dye_density", "silver", "film_only"]


# -----------------------------
# Utility math
# -----------------------------

def srgb_to_linear(x: Array) -> Array:
    """Convert sRGB in [0, 1] to linear RGB."""
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: Array) -> Array:
    """Convert linear RGB in [0, inf) to display sRGB in [0, 1]."""
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * (x ** (1 / 2.4)) - 0.055)


def sigmoid(x: Array, midpoint: float, slope: float) -> Array:
    return 1.0 / (1.0 + np.exp(-slope * (x - midpoint)))


def soft_clip(x: Array, shoulder: float = 0.85, strength: float = 2.0) -> Array:
    """Compress high values into a film-like shoulder."""
    x = np.asarray(x)
    below = x <= shoulder
    y = np.empty_like(x)
    y[below] = x[below]
    y[~below] = shoulder + (1.0 - shoulder) * (1.0 - np.exp(-strength * (x[~below] - shoulder)))
    return np.clip(y, 0.0, 1.0)


def normalize_noise(x: Array) -> Array:
    x = x.astype(np.float32)
    return (x - x.mean()) / (x.std() + 1e-6)


def blurred_noise(
    shape: tuple[int, int, int],
    rng: np.random.Generator,
    radius: float,
) -> Array:
    """
    Spatially correlated zero-mean unit-std noise.
    Uses PIL blur to avoid scipy.
    """
    h, w, c = shape
    raw = rng.normal(0.0, 1.0, (h, w, c)).astype(np.float32)
    if radius <= 0:
        return normalize_noise(raw)

    out = np.empty_like(raw)
    for i in range(c):
        plane = raw[..., i]
        pmin, pmax = float(plane.min()), float(plane.max())
        img = Image.fromarray(np.uint8(255 * (plane - pmin) / (pmax - pmin + 1e-9)))
        img = img.filter(ImageFilter.GaussianBlur(radius=float(radius)))
        arr = np.asarray(img).astype(np.float32) / 255.0
        out[..., i] = normalize_noise(arr)
    return out


def load_image(path: str | Path, max_size: int | None = None) -> Array:
    """Load JPEG/PNG/TIFF/etc. through Pillow, preserving EXIF orientation."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba).convert("RGB")
    else:
        img = img.convert("RGB")

    if max_size is not None:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    return np.asarray(img).astype(np.float32) / 255.0


def save_image(arr: Array, path: str | Path, quality: int = 95) -> None:
    arr = np.clip(arr, 0.0, 1.0)
    img = Image.fromarray(np.uint8(np.round(arr * 255.0)))
    path = Path(path)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        img.save(path, quality=quality, subsampling=0, optimize=True)
    else:
        img.save(path)


# -----------------------------
# Film settings
# -----------------------------

@dataclass(frozen=True)
class FilmSettings:
    # Exposure and speed
    iso: float = 400.0
    exposure_ev: float = 0.0

    # Rows are film layers: red-sensitive, green-sensitive, blue-sensitive.
    # Columns are incoming linear RGB channels.
    sensitivity_matrix: tuple[tuple[float, float, float], ...] = (
        (1.00, 0.045, 0.018),
        (0.035, 1.00, 0.040),
        (0.018, 0.055, 1.00),
    )

    # Layer exposure bias in stops: red, green, blue-sensitive layers.
    layer_ev_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)

    # Crystal / latent image model
    crystal_density: float = 26000.0    # higher = finer grain, less harsh noise
    photon_scale: float = 10.0
    latent_threshold: float = 0.50
    latent_softness: float = 5.0

    # Development model
    developer_activity: float = 0.72
    development_time: float = 1.0
    contrast: float = 0.68
    shoulder: float = 0.70
    toe: float = 0.012

    # Dye density model: red-sensitive layer -> cyan, green -> magenta, blue -> yellow
    max_dye_density: tuple[float, float, float] = (0.76, 0.72, 0.68)
    dye_gamma: tuple[float, float, float] = (0.86, 0.86, 0.86)
    dye_contamination: tuple[tuple[float, float, float], ...] = (
        (1.00, 0.040, 0.018),
        (0.035, 1.00, 0.025),
        (0.018, 0.045, 1.00),
    )

    # Mask and base
    orange_mask_rgb_density: tuple[float, float, float] = (0.035, 0.090, 0.160)
    base_fog_density: float = 0.012

    # Realistic grain / dye-cloud texture
    # grain_strength is intentionally visible at default, but not destructive.
    grain_strength: float = 0.34
    grain_size_px: float = 0.85
    micro_grain_size_px: float = 0.18
    dye_cloud_size_px: float = 0.75
    dye_cloud_blur_px: float = 0.28
    chroma_grain: float = 0.22        # lower = more luminance/shared grain, less RGB speckle
    density_grain: float = 0.52       # grain rides on dye density, not flat overlay

    # Halation
    halation_strength: float = 0.004
    halation_radius_px: float = 7.0

    # Scan / print model
    scan_exposure: float = 1.0
    scan_contrast: float = 0.985
    scan_saturation: float = 0.985
    scan_temperature: float = 0.0
    black_point: float = 0.0
    white_point: float = 1.0

    # Positive output blend. Lower = closer to original JPEG.
    effect_strength: float = 0.38

    seed: int = 1


PRESETS: dict[str, FilmSettings] = {
    "neutral": FilmSettings(),

    # Slightly warmer/softer than neutral, still JPEG-safe.
    "portraish": FilmSettings(
        developer_activity=0.70,
        contrast=0.64,
        shoulder=0.68,
        max_dye_density=(0.72, 0.68, 0.62),
        orange_mask_rgb_density=(0.040, 0.105, 0.180),
        grain_strength=0.30,
        grain_size_px=0.78,
        dye_cloud_size_px=0.80,
        scan_saturation=0.96,
        scan_temperature=0.10,
        effect_strength=0.36,
    ),

    # Cleaner, more saturated, finer-grained.
    "ektarish": FilmSettings(
        developer_activity=0.76,
        contrast=0.76,
        shoulder=0.76,
        max_dye_density=(0.84, 0.80, 0.74),
        grain_strength=0.22,
        grain_size_px=0.55,
        dye_cloud_size_px=0.55,
        scan_saturation=1.07,
        effect_strength=0.42,
    ),

    # Softer scan, mild halation, visible but controlled grain.
    "cinema": FilmSettings(
        developer_activity=0.68,
        contrast=0.60,
        shoulder=0.64,
        max_dye_density=(0.70, 0.66, 0.62),
        orange_mask_rgb_density=(0.030, 0.080, 0.145),
        grain_strength=0.38,
        grain_size_px=0.95,
        dye_cloud_size_px=1.00,
        halation_strength=0.020,
        halation_radius_px=13.0,
        scan_saturation=0.94,
        scan_contrast=0.96,
        effect_strength=0.40,
    ),

    # Stronger contrast/saturation, not a true E-6 model.
    "slideish": FilmSettings(
        developer_activity=0.84,
        contrast=0.92,
        shoulder=0.88,
        max_dye_density=(0.95, 0.92, 0.88),
        orange_mask_rgb_density=(0.0, 0.0, 0.0),
        base_fog_density=0.006,
        grain_strength=0.20,
        grain_size_px=0.45,
        dye_cloud_size_px=0.45,
        scan_saturation=1.16,
        scan_contrast=1.04,
        effect_strength=0.48,
    ),
}


# -----------------------------
# Simulation stages
# -----------------------------

def expose_layers(scene_srgb: Array, settings: FilmSettings) -> Array:
    """
    Convert display RGB scene into film-layer exposure values.

    Returns HxWx3 in layer order:
        red-sensitive, green-sensitive, blue-sensitive.
    """
    scene_linear = srgb_to_linear(scene_srgb)

    # Optional halation: mostly red/orange spread from strong highlights.
    if settings.halation_strength > 0:
        luminance = (
            0.2126 * scene_linear[..., 0]
            + 0.7152 * scene_linear[..., 1]
            + 0.0722 * scene_linear[..., 2]
        )
        highlights = np.clip((luminance - 0.72) / 0.28, 0.0, 1.0) ** 2
        h_img = Image.fromarray(np.uint8(highlights * 255.0))
        h_img = h_img.filter(ImageFilter.GaussianBlur(radius=settings.halation_radius_px))
        halo = np.asarray(h_img).astype(np.float32) / 255.0

        scene_linear = scene_linear.copy()
        scene_linear[..., 0] += settings.halation_strength * halo
        scene_linear[..., 1] += settings.halation_strength * 0.32 * halo

    matrix = np.array(settings.sensitivity_matrix, dtype=np.float32)
    exposures = np.tensordot(scene_linear, matrix.T, axes=([2], [0]))

    iso_factor = settings.iso / 400.0
    ev_factor = 2.0 ** settings.exposure_ev
    layer_bias = np.array([2.0 ** b for b in settings.layer_ev_bias], dtype=np.float32)

    return np.clip(exposures * iso_factor * ev_factor * layer_bias, 0.0, None)


def make_emulsion_grain(shape: tuple[int, int, int], settings: FilmSettings, rng: np.random.Generator) -> Array:
    """
    Build grain from multiple scales:
        - shared luminance-like clumps
        - weak independent layer grain
        - fine micro-grain

    This avoids pure RGB digital noise.
    """
    h, w, _ = shape

    shared = blurred_noise((h, w, 1), rng, settings.grain_size_px)
    shared = np.repeat(shared, 3, axis=2)

    layer = blurred_noise((h, w, 3), rng, settings.dye_cloud_size_px)
    micro = blurred_noise((h, w, 3), rng, settings.micro_grain_size_px)

    shared_part = (1.0 - settings.chroma_grain) * shared
    chroma_part = settings.chroma_grain * layer
    micro_part = 0.25 * micro

    return normalize_noise(shared_part + chroma_part + micro_part)


def form_latent_image(layer_exposures: Array, settings: FilmSettings) -> Array:
    """
    Stochastic latent-image formation.

    The simulator approximates microscopic crystals with exposure-dependent
    probabilities and spatially clustered grain.
    """
    rng = np.random.default_rng(settings.seed)

    activation = 1.0 - np.exp(
        -settings.photon_scale * layer_exposures / max(settings.crystal_density / 1000.0, 1e-6)
    )

    grain = make_emulsion_grain(layer_exposures.shape, settings, rng)

    # Grain is strongest in mid exposure and weaker in empty shadows / clipped highlights.
    exposure_weight = np.clip(4.0 * activation * (1.0 - activation), 0.0, 1.0)
    exposure_weight = 0.25 + 0.75 * exposure_weight

    noise_scale = settings.grain_strength / np.sqrt(max(settings.crystal_density / 1000.0, 1e-6))
    noisy_activation = activation + noise_scale * 0.65 * grain * exposure_weight

    latent = sigmoid(noisy_activation, settings.latent_threshold, settings.latent_softness)

    # Low-level shot variation, kept mostly luminance-like by being tiny.
    shot_sigma = settings.grain_strength * 0.012 / np.sqrt(max(settings.crystal_density / 1000.0, 1e-6))
    latent += rng.normal(0.0, shot_sigma, latent.shape).astype(np.float32)

    return np.clip(latent, 0.0, 1.0)


def develop_silver(latent: Array, settings: FilmSettings) -> Array:
    """Development converts exposed grains into metallic silver density."""
    activity = settings.developer_activity * settings.development_time
    x = latent * activity

    x = np.clip((x - settings.toe) / max(1.0 - settings.toe, 1e-6), 0.0, 1.0)
    x = x ** (1.0 / max(settings.contrast, 1e-6))
    x = soft_clip(x, shoulder=settings.shoulder, strength=2.4)
    return np.clip(x, 0.0, 1.0)


def form_dyes(silver_density: Array, settings: FilmSettings) -> Array:
    """
    Oxidized developer plus dye couplers create C/M/Y dye densities.

    Returns HxWx3 in dye order:
        cyan, magenta, yellow.
    """
    rng = np.random.default_rng(settings.seed + 1000)

    max_density = np.array(settings.max_dye_density, dtype=np.float32)
    gamma = np.array(settings.dye_gamma, dtype=np.float32)

    base_dyes = max_density * np.clip(silver_density, 0.0, 1.0) ** gamma

    # Dye clouds are not a flat noise overlay; they modulate density.
    cloud = make_emulsion_grain(base_dyes.shape, settings, rng)
    density_weight = np.clip(base_dyes / (max_density + 1e-6), 0.0, 1.0)
    midtone_weight = np.sqrt(np.clip(density_weight * (1.0 - 0.35 * density_weight), 0.0, 1.0))
    modulation = 1.0 + settings.grain_strength * settings.density_grain * cloud * midtone_weight

    dyes = np.clip(base_dyes * modulation, 0.0, None)

    # Dye clouds are larger than silver grains, so blur slightly after modulation.
    if settings.dye_cloud_blur_px > 0:
        blurred = np.empty_like(dyes)
        for c in range(3):
            scale = max(float(max_density[c]), 1e-6)
            plane = np.clip(dyes[..., c] / scale, 0.0, 1.0)
            img = Image.fromarray(np.uint8(plane * 255.0))
            img = img.filter(ImageFilter.GaussianBlur(radius=settings.dye_cloud_blur_px))
            blurred[..., c] = (np.asarray(img).astype(np.float32) / 255.0) * scale
        dyes = blurred

    return np.clip(dyes, 0.0, None)


def bleach_and_fix(silver_density: Array, dyes_cmy: Array, settings: FilmSettings) -> tuple[Array, Array]:
    """
    Bleach/fix removes metallic silver and undeveloped silver halide.
    We return zeroed silver and unchanged dyes.
    """
    removed_silver = np.zeros_like(silver_density)
    return removed_silver, dyes_cmy


def cmy_dyes_to_negative_rgb_transmission(dyes_cmy: Array, settings: FilmSettings) -> Array:
    """
    Convert C/M/Y dye densities into RGB negative transmission.

    Density D means transmission T = 10^-D.
    """
    contamination = np.array(settings.dye_contamination, dtype=np.float32)

    # RGB density receives contributions from C/M/Y dye clouds.
    rgb_density = np.tensordot(dyes_cmy, contamination, axes=([2], [0]))
    rgb_density += np.array(settings.orange_mask_rgb_density, dtype=np.float32)
    rgb_density += settings.base_fog_density

    transmission = 10.0 ** (-rgb_density)
    return np.clip(transmission, 0.0, 1.0)


def scan_negative_to_positive(negative_rgb: Array, settings: FilmSettings) -> Array:
    """
    Invert and lightly grade the negative into a display-positive image.

    Important: the percentile range is deliberately wide. Tight percentile
    normalization was what caused gray, crushed, contrasty output.
    """
    density = -np.log10(np.clip(negative_rgb, 1e-6, 1.0))
    mask = np.array(settings.orange_mask_rgb_density, dtype=np.float32) + settings.base_fog_density
    density = np.clip(density - mask, 0.0, None)

    lo = np.percentile(density.reshape(-1, 3), 0.02, axis=0)
    hi = np.percentile(density.reshape(-1, 3), 99.98, axis=0)
    pos = (density - lo) / (hi - lo + 1e-6)
    pos = np.clip(pos, 0.0, 1.0)

    pos = np.clip(pos * settings.scan_exposure, 0.0, 1.0)
    pos = np.clip((pos - 0.5) * settings.scan_contrast + 0.5, 0.0, 1.0)

    pos = (pos - settings.black_point) / max(settings.white_point - settings.black_point, 1e-6)
    pos = np.clip(pos, 0.0, 1.0)

    lum = 0.2126 * pos[..., 0:1] + 0.7152 * pos[..., 1:2] + 0.0722 * pos[..., 2:3]
    pos = lum + settings.scan_saturation * (pos - lum)

    temp = settings.scan_temperature
    pos[..., 0] *= 1.0 + 0.08 * temp
    pos[..., 2] *= 1.0 - 0.08 * temp

    return np.clip(linear_to_srgb(pos), 0.0, 1.0)


def add_visible_print_grain(positive_srgb: Array, settings: FilmSettings) -> Array:
    """
    Final optical grain visibility.

    This is still driven by the same grain settings, but it is applied in optical
    density-like space after scanning so that grain remains visible even when
    effect_strength is low. It is mostly luminance grain, not RGB sensor noise.
    """
    if settings.grain_strength <= 0:
        return positive_srgb

    rng = np.random.default_rng(settings.seed + 2000)
    h, w = positive_srgb.shape[:2]

    coarse = blurred_noise((h, w, 1), rng, settings.grain_size_px)
    fine = blurred_noise((h, w, 1), rng, settings.micro_grain_size_px)
    layer = blurred_noise((h, w, 3), rng, settings.dye_cloud_size_px)

    lum_grain = normalize_noise(0.85 * coarse + 0.35 * fine)
    chroma_grain = layer * settings.chroma_grain * 0.30
    grain = lum_grain + chroma_grain

    linear = srgb_to_linear(positive_srgb)
    lum = 0.2126 * linear[..., 0:1] + 0.7152 * linear[..., 1:2] + 0.0722 * linear[..., 2:3]

    # Visible mostly in shadows/midtones, less in clipped whites.
    visibility = np.clip(1.0 - 0.65 * lum, 0.25, 1.0)

    amount = 0.055 * settings.grain_strength
    noisy = linear * (1.0 + amount * grain * visibility)
    return np.clip(linear_to_srgb(noisy), 0.0, 1.0)


def render_dye_density_debug(dyes_cmy: Array) -> Array:
    """Visualize dye densities as false-color CMY absorptions."""
    maxv = np.percentile(dyes_cmy, 99.5) + 1e-6
    cmy = np.clip(dyes_cmy / maxv, 0.0, 1.0)
    rgb = 1.0 - np.stack([cmy[..., 0], cmy[..., 1], cmy[..., 2]], axis=-1)
    return np.clip(rgb, 0.0, 1.0)


def render_silver_debug(silver_density: Array) -> Array:
    """Visualize developed silver before bleach/fix."""
    gray = np.mean(silver_density, axis=2)
    gray = gray / (np.percentile(gray, 99.5) + 1e-6)
    rgb = np.repeat((1.0 - np.clip(gray, 0.0, 1.0))[..., None], 3, axis=2)
    return rgb


def render_layer_image(layer_data: Array) -> Array:
    """Normalize 3-channel layer data for debug viewing."""
    arr = np.asarray(layer_data, dtype=np.float32)
    flat = arr.reshape(-1, arr.shape[-1])
    lo = np.percentile(flat, 0.1, axis=0)
    hi = np.percentile(flat, 99.9, axis=0)
    return np.clip((arr - lo) / (hi - lo + 1e-6), 0.0, 1.0)


def render_negative_density_debug(negative_rgb: Array, settings: FilmSettings) -> Array:
    """Visualize the orange-masked negative as density rather than transmission."""
    density = -np.log10(np.clip(negative_rgb, 1e-6, 1.0))
    density = density / (np.percentile(density, 99.8) + 1e-6)
    return np.clip(density, 0.0, 1.0)


def simulate_film_stages(scene_srgb: Array, settings: FilmSettings) -> dict[str, Array]:
    """Run the full pipeline and return a displayable image for each major stage."""
    stages: dict[str, Array] = {}
    stages["00_input"] = np.clip(scene_srgb, 0.0, 1.0)

    exposures = expose_layers(scene_srgb, settings)
    stages["01_layer_exposures_rgb_sensitive"] = render_layer_image(exposures)

    latent = form_latent_image(exposures, settings)
    stages["02_latent_image_probability"] = render_layer_image(latent)

    silver = develop_silver(latent, settings)
    stages["03_developed_silver_before_bleach"] = render_silver_debug(silver)

    dyes = form_dyes(silver, settings)
    stages["04_cmy_dye_density"] = render_dye_density_debug(dyes)

    removed_silver, fixed_dyes = bleach_and_fix(silver, dyes, settings)
    stages["05_bleached_silver_removed"] = render_silver_debug(removed_silver)
    stages["06_fixed_cmy_dye_density"] = render_dye_density_debug(fixed_dyes)

    negative = cmy_dyes_to_negative_rgb_transmission(fixed_dyes, settings)
    stages["07_orange_masked_negative_transmission"] = negative
    stages["08_negative_density_debug"] = render_negative_density_debug(negative, settings)

    film_positive_no_grain = scan_negative_to_positive(negative, settings)
    stages["09_scanned_positive_no_final_grain"] = film_positive_no_grain

    film_positive = add_visible_print_grain(film_positive_no_grain, settings)
    stages["10_film_positive_with_print_grain"] = film_positive

    strength = np.clip(settings.effect_strength, 0.0, 1.0)
    blended_no_final_grain = scene_srgb * (1.0 - strength) + film_positive * strength
    stages["11_blended_with_original"] = np.clip(blended_no_final_grain, 0.0, 1.0)

    final = add_visible_print_grain(blended_no_final_grain, replace(settings, grain_strength=settings.grain_strength * 0.55))
    stages["12_final_output"] = np.clip(final, 0.0, 1.0)

    return stages


def save_all_stages(stages: dict[str, Array], output_path: str | Path, stages_dir: str | Path | None, quality: int = 95) -> None:
    """Save each stage next to the output or in a user-specified folder."""
    output_path = Path(output_path)
    if stages_dir is None:
        base = output_path.with_suffix("")
        folder = base.parent / f"{base.name}_stages"
    else:
        folder = Path(stages_dir)
    folder.mkdir(parents=True, exist_ok=True)

    for name, image in stages.items():
        save_image(image, folder / f"{name}.jpg", quality=quality)


def simulate_film(scene_srgb: Array, settings: FilmSettings, output_stage: OutputStage = "positive") -> Array:
    stages = simulate_film_stages(scene_srgb, settings)

    if output_stage == "negative":
        return stages["07_orange_masked_negative_transmission"]
    if output_stage == "dye_density":
        return stages["06_fixed_cmy_dye_density"]
    if output_stage == "silver":
        return stages["03_developed_silver_before_bleach"]
    if output_stage == "film_only":
        return stages["10_film_positive_with_print_grain"]
    return stages["12_final_output"]


# -----------------------------
# CLI
# -----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="JPEG-friendly physically-inspired color film simulator")
    p.add_argument("input", help="Input image path")
    p.add_argument("output", nargs="?", default=None, help="Output image path. Default: <input_stem>_film.jpg")
    p.add_argument("--preset", choices=sorted(PRESETS.keys()), default="neutral")
    p.add_argument("--output-stage", choices=["positive", "negative", "dye_density", "silver", "film_only"], default="positive")
    p.add_argument("--max-size", type=int, default=None, help="Resize largest side before processing")
    p.add_argument("--quality", type=int, default=95, help="JPEG quality")
    p.add_argument("--save-stages", action="store_true", help="Save an image after every simulation stage")
    p.add_argument("--stages-dir", default=None, help="Folder for stage images. Default: <output_name>_stages")

    # Common controls
    p.add_argument("--iso", type=float, default=None)
    p.add_argument("--exposure", type=float, default=None, help="Exposure compensation in EV/stops")
    p.add_argument("--contrast", type=float, default=None)
    p.add_argument("--developer-activity", type=float, default=None)
    p.add_argument("--development-time", type=float, default=None)
    p.add_argument("--grain", type=float, default=None, help="Overall grain strength")
    p.add_argument("--grain-size", type=float, default=None, help="Main grain size in pixels")
    p.add_argument("--micro-grain-size", type=float, default=None, help="Fine grain size in pixels")
    p.add_argument("--dye-cloud-size", type=float, default=None, help="Dye cloud grain size in pixels")
    p.add_argument("--crystal-density", type=float, default=None, help="Higher = finer/cleaner grain")
    p.add_argument("--halation", type=float, default=None)
    p.add_argument("--halation-radius", type=float, default=None)
    p.add_argument("--saturation", type=float, default=None)
    p.add_argument("--temperature", type=float, default=None, help="Negative cooler, positive warmer")
    p.add_argument("--scan-contrast", type=float, default=None)
    p.add_argument("--scan-exposure", type=float, default=None)
    p.add_argument("--effect-strength", type=float, default=None, help="0 = original image, 1 = full film simulation")
    p.add_argument("--seed", type=int, default=None)

    return p


def apply_cli_overrides(settings: FilmSettings, args: argparse.Namespace) -> FilmSettings:
    changes = {}
    mapping = {
        "iso": "iso",
        "exposure": "exposure_ev",
        "contrast": "contrast",
        "developer_activity": "developer_activity",
        "development_time": "development_time",
        "grain": "grain_strength",
        "grain_size": "grain_size_px",
        "micro_grain_size": "micro_grain_size_px",
        "dye_cloud_size": "dye_cloud_size_px",
        "crystal_density": "crystal_density",
        "halation": "halation_strength",
        "halation_radius": "halation_radius_px",
        "saturation": "scan_saturation",
        "temperature": "scan_temperature",
        "scan_contrast": "scan_contrast",
        "scan_exposure": "scan_exposure",
        "effect_strength": "effect_strength",
        "seed": "seed",
    }
    for arg_name, setting_name in mapping.items():
        value = getattr(args, arg_name)
        if value is not None:
            changes[setting_name] = value
    return replace(settings, **changes)


def default_output_path(input_path: str | Path) -> str:
    """Return <input folder>/<input stem>_film.jpg."""
    in_path = Path(input_path)
    return str(in_path.with_name(f"{in_path.stem}_film.jpg"))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.output is None:
        args.output = default_output_path(args.input)

    settings = apply_cli_overrides(PRESETS[args.preset], args)
    scene = load_image(args.input, max_size=args.max_size)
    if args.save_stages:
        stages = simulate_film_stages(scene, settings)
        save_all_stages(stages, args.output, args.stages_dir, quality=args.quality)
        result = simulate_film(scene, settings, output_stage=args.output_stage)
    else:
        result = simulate_film(scene, settings, output_stage=args.output_stage)

    save_image(result, args.output, quality=args.quality)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
