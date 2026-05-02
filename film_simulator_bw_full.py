#!/usr/bin/env python3
"""
film_simulator_bw.py

JPEG/PNG/TIFF-friendly black-and-white photographic film simulator.

This is the black-and-white equivalent of the color simulator. It is tuned for
already-processed digital images. It keeps the source image mostly intact by
default, then adds a controllable B&W film process:

1. RGB scene light is converted to panchromatic B&W emulsion exposure.
2. Silver-halide crystals receive stochastic exposure.
3. A latent image forms.
4. Development creates metallic silver density.
5. Fixing/washing removes undeveloped silver halide, leaving developed silver.
6. The negative is scanned/printed back to a positive image.
7. Optical/print grain is added.
8. The scanned result is blended with a normal B&W conversion of the source.

Install:
    pip install numpy pillow

Examples:
    python film_simulator_bw.py input.jpg
    python film_simulator_bw.py input.jpg output.jpg
    python film_simulator_bw.py input.jpg --preset hp5 --grain 0.45
    python film_simulator_bw.py input.jpg --preset tri-x --effect-strength 0.65
    python film_simulator_bw.py input.jpg --save-stages

Defaults are subtle. Raise --grain and --effect-strength for a stronger film look.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

Array = np.ndarray
OutputStage = Literal[
    "positive",
    "negative",
    "silver",
    "latent",
    "film_only",
    "base_bw",
]


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


def render_gray(gray: Array) -> Array:
    """Return HxWx3 display image from HxW grayscale array."""
    gray = np.clip(gray, 0.0, 1.0)
    return np.repeat(gray[..., None], 3, axis=2)


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
# B&W film settings
# -----------------------------

@dataclass(frozen=True)
class BWFilmSettings:
    # Exposure and speed
    iso: float = 400.0
    exposure_ev: float = 0.0

    # Panchromatic spectral response to incoming linear RGB.
    # Change this to imitate filters:
    #   red filter:    (0.55, 0.35, 0.10)
    #   yellow filter: (0.42, 0.48, 0.10)
    #   blue filter:   (0.10, 0.30, 0.60)
    spectral_sensitivity: tuple[float, float, float] = (0.28, 0.57, 0.15)

    # Crystal / latent image model
    crystal_density: float = 24000.0
    photon_scale: float = 10.0
    latent_threshold: float = 0.50
    latent_softness: float = 5.2

    # Development model
    developer_activity: float = 0.76
    development_time: float = 1.0
    contrast: float = 0.78
    shoulder: float = 0.74
    toe: float = 0.014

    # Negative density model
    max_silver_density: float = 0.90
    silver_gamma: float = 0.88
    base_fog_density: float = 0.020

    # Grain model
    grain_strength: float = 0.34
    grain_size_px: float = 0.85
    micro_grain_size_px: float = 0.18
    clump_size_px: float = 1.10
    density_grain: float = 0.62

    # Optional halation / highlight glow before exposure
    halation_strength: float = 0.003
    halation_radius_px: float = 7.0

    # Scan / print model
    scan_exposure: float = 1.0
    scan_contrast: float = 0.99
    print_gamma: float = 1.0
    black_point: float = 0.0
    white_point: float = 1.0

    # Output toning.
    # neutral = pure grayscale, warm = faint warm paper, selenium = faint cool shadows.
    tone: Literal["neutral", "warm", "selenium"] = "neutral"
    tone_strength: float = 0.0

    # Positive output blend. Lower = closer to normal B&W conversion.
    effect_strength: float = 0.42

    seed: int = 1


PRESETS: dict[str, BWFilmSettings] = {
    "neutral": BWFilmSettings(),

    # Softer, classic HP5-ish negative.
    "hp5": BWFilmSettings(
        iso=400.0,
        spectral_sensitivity=(0.29, 0.56, 0.15),
        developer_activity=0.74,
        contrast=0.72,
        shoulder=0.70,
        max_silver_density=0.86,
        grain_strength=0.42,
        grain_size_px=1.00,
        clump_size_px=1.25,
        scan_contrast=0.97,
        effect_strength=0.46,
    ),

    # Punchier Tri-X-ish response.
    "tri-x": BWFilmSettings(
        iso=400.0,
        spectral_sensitivity=(0.30, 0.55, 0.15),
        developer_activity=0.84,
        contrast=0.92,
        shoulder=0.82,
        max_silver_density=1.02,
        grain_strength=0.48,
        grain_size_px=0.95,
        clump_size_px=1.10,
        scan_contrast=1.05,
        effect_strength=0.52,
    ),

    # Fine-grain low-speed look.
    "fine": BWFilmSettings(
        iso=100.0,
        crystal_density=42000.0,
        photon_scale=11.0,
        developer_activity=0.72,
        contrast=0.76,
        max_silver_density=0.82,
        grain_strength=0.18,
        grain_size_px=0.45,
        micro_grain_size_px=0.12,
        clump_size_px=0.65,
        effect_strength=0.38,
    ),

    # High-speed rougher look.
    "pushed": BWFilmSettings(
        iso=1600.0,
        developer_activity=0.98,
        development_time=1.15,
        contrast=1.08,
        shoulder=0.86,
        max_silver_density=1.12,
        grain_strength=0.70,
        grain_size_px=1.35,
        clump_size_px=1.70,
        scan_contrast=1.08,
        effect_strength=0.62,
    ),

    # Slight warm paper tone.
    "warm-paper": BWFilmSettings(
        developer_activity=0.74,
        contrast=0.74,
        grain_strength=0.30,
        tone="warm",
        tone_strength=0.28,
        effect_strength=0.44,
    ),
}


# -----------------------------
# B&W simulation stages
# -----------------------------

def base_bw_conversion(scene_srgb: Array, settings: BWFilmSettings) -> Array:
    """Normal B&W conversion from source, using the same spectral weights."""
    scene_linear = srgb_to_linear(scene_srgb)
    weights = np.array(settings.spectral_sensitivity, dtype=np.float32)
    weights = weights / (weights.sum() + 1e-6)
    gray_linear = np.tensordot(scene_linear, weights, axes=([2], [0]))
    return np.clip(linear_to_srgb(gray_linear), 0.0, 1.0)


def expose_emulsion(scene_srgb: Array, settings: BWFilmSettings) -> Array:
    """
    Convert RGB scene to single panchromatic emulsion exposure.

    Returns HxW exposure array.
    """
    scene_linear = srgb_to_linear(scene_srgb)

    if settings.halation_strength > 0:
        lum = (
            0.2126 * scene_linear[..., 0]
            + 0.7152 * scene_linear[..., 1]
            + 0.0722 * scene_linear[..., 2]
        )
        highlights = np.clip((lum - 0.74) / 0.26, 0.0, 1.0) ** 2
        h_img = Image.fromarray(np.uint8(highlights * 255.0))
        h_img = h_img.filter(ImageFilter.GaussianBlur(radius=settings.halation_radius_px))
        halo = np.asarray(h_img).astype(np.float32) / 255.0
        scene_linear = scene_linear.copy()
        # B&W halation adds exposure, not color.
        scene_linear += settings.halation_strength * halo[..., None]

    weights = np.array(settings.spectral_sensitivity, dtype=np.float32)
    weights = weights / (weights.sum() + 1e-6)
    exposure = np.tensordot(scene_linear, weights, axes=([2], [0]))

    iso_factor = settings.iso / 400.0
    ev_factor = 2.0 ** settings.exposure_ev
    return np.clip(exposure * iso_factor * ev_factor, 0.0, None)


def make_bw_emulsion_grain(shape_hw: tuple[int, int], settings: BWFilmSettings, rng: np.random.Generator) -> Array:
    """
    Build B&W grain from several scales:
        - clumped grains
        - main silver grain
        - fine micro grain
    """
    h, w = shape_hw
    clumps = blurred_noise((h, w, 1), rng, settings.clump_size_px)[..., 0]
    main = blurred_noise((h, w, 1), rng, settings.grain_size_px)[..., 0]
    micro = blurred_noise((h, w, 1), rng, settings.micro_grain_size_px)[..., 0]
    return normalize_noise(0.55 * clumps + 0.75 * main + 0.22 * micro)


def form_latent_image(exposure: Array, settings: BWFilmSettings) -> Array:
    """
    Stochastic latent-image formation.

    B&W film has one main silver-halide image layer in this simplified model.
    """
    rng = np.random.default_rng(settings.seed)

    activation = 1.0 - np.exp(
        -settings.photon_scale * exposure / max(settings.crystal_density / 1000.0, 1e-6)
    )

    grain = make_bw_emulsion_grain(exposure.shape, settings, rng)

    # Grain matters most around mid exposure. Avoid destroying empty shadows and clipped whites.
    exposure_weight = np.clip(4.0 * activation * (1.0 - activation), 0.0, 1.0)
    exposure_weight = 0.22 + 0.78 * exposure_weight

    noise_scale = settings.grain_strength / np.sqrt(max(settings.crystal_density / 1000.0, 1e-6))
    noisy_activation = activation + noise_scale * 0.78 * grain * exposure_weight

    latent = sigmoid(noisy_activation, settings.latent_threshold, settings.latent_softness)

    shot_sigma = settings.grain_strength * 0.014 / np.sqrt(max(settings.crystal_density / 1000.0, 1e-6))
    latent += rng.normal(0.0, shot_sigma, latent.shape).astype(np.float32)

    return np.clip(latent, 0.0, 1.0)


def develop_silver(latent: Array, settings: BWFilmSettings) -> Array:
    """Development converts exposed grains into metallic silver density."""
    activity = settings.developer_activity * settings.development_time
    x = latent * activity

    x = np.clip((x - settings.toe) / max(1.0 - settings.toe, 1e-6), 0.0, 1.0)
    x = x ** (1.0 / max(settings.contrast, 1e-6))
    x = soft_clip(x, shoulder=settings.shoulder, strength=2.4)

    silver = settings.max_silver_density * (np.clip(x, 0.0, 1.0) ** settings.silver_gamma)
    return np.clip(silver, 0.0, None)


def fix_and_wash(silver_density: Array, settings: BWFilmSettings) -> Array:
    """
    In B&W film, fixing removes undeveloped silver halide.
    Developed metallic silver remains and forms the negative image.

    So unlike color negative film, this stage is not blank/white.
    """
    return np.clip(silver_density, 0.0, None)


def silver_to_negative_transmission(silver_density: Array, settings: BWFilmSettings) -> Array:
    """
    Convert developed silver density to negative transmission.

    Density D means transmission T = 10^-D.
    """
    density = silver_density + settings.base_fog_density
    transmission = 10.0 ** (-density)
    return np.clip(transmission, 0.0, 1.0)


def scan_negative_to_positive(negative_transmission: Array, settings: BWFilmSettings) -> Array:
    """
    Invert and lightly grade the B&W negative into a display-positive image.
    """
    density = -np.log10(np.clip(negative_transmission, 1e-6, 1.0))
    density = np.clip(density - settings.base_fog_density, 0.0, None)

    lo = np.percentile(density, 0.02)
    hi = np.percentile(density, 99.98)
    pos = (density - lo) / (hi - lo + 1e-6)
    pos = np.clip(pos, 0.0, 1.0)

    pos = np.clip(pos * settings.scan_exposure, 0.0, 1.0)
    pos = np.clip((pos - 0.5) * settings.scan_contrast + 0.5, 0.0, 1.0)
    pos = (pos - settings.black_point) / max(settings.white_point - settings.black_point, 1e-6)
    pos = np.clip(pos, 0.0, 1.0)

    if settings.print_gamma != 1.0:
        pos = np.clip(pos, 0.0, 1.0) ** (1.0 / max(settings.print_gamma, 1e-6))

    return np.clip(linear_to_srgb(pos), 0.0, 1.0)


def add_visible_print_grain(positive_gray_srgb: Array, settings: BWFilmSettings) -> Array:
    """
    Final optical grain visibility in the positive output.

    This keeps grain visible even with lower effect_strength, without RGB speckle.
    """
    if settings.grain_strength <= 0:
        return positive_gray_srgb

    rng = np.random.default_rng(settings.seed + 2000)
    h, w = positive_gray_srgb.shape[:2]

    coarse = blurred_noise((h, w, 1), rng, settings.grain_size_px)[..., 0]
    clump = blurred_noise((h, w, 1), rng, settings.clump_size_px)[..., 0]
    fine = blurred_noise((h, w, 1), rng, settings.micro_grain_size_px)[..., 0]
    grain = normalize_noise(0.60 * clump + 0.75 * coarse + 0.30 * fine)

    linear = srgb_to_linear(positive_gray_srgb)

    # Visible mostly in shadows and midtones, less in high whites.
    visibility = np.clip(1.0 - 0.65 * linear, 0.25, 1.0)

    amount = 0.070 * settings.grain_strength
    noisy = linear * (1.0 + amount * grain * visibility)
    return np.clip(linear_to_srgb(noisy), 0.0, 1.0)


def apply_tone(gray_srgb: Array, settings: BWFilmSettings) -> Array:
    """Apply subtle warm or selenium tone. Returns RGB."""
    gray = np.clip(gray_srgb, 0.0, 1.0)
    base = render_gray(gray)

    strength = np.clip(settings.tone_strength, 0.0, 1.0)
    if settings.tone == "neutral" or strength <= 0:
        return base

    if settings.tone == "warm":
        tone_rgb = np.array([1.055, 1.015, 0.955], dtype=np.float32)
        toned = base * (1.0 + strength * (tone_rgb - 1.0))
        return np.clip(toned, 0.0, 1.0)

    if settings.tone == "selenium":
        # Mostly cools shadows without turning highlights blue.
        shadow = np.clip(1.0 - gray, 0.0, 1.0)[..., None]
        tone_rgb = np.array([0.970, 0.990, 1.045], dtype=np.float32)
        toned = base * (1.0 + strength * shadow * (tone_rgb - 1.0))
        return np.clip(toned, 0.0, 1.0)

    return base


def render_exposure_debug(exposure: Array) -> Array:
    lo = np.percentile(exposure, 0.1)
    hi = np.percentile(exposure, 99.9)
    return render_gray(np.clip((exposure - lo) / (hi - lo + 1e-6), 0.0, 1.0))


def render_density_debug(density: Array) -> Array:
    scale = np.percentile(density, 99.8) + 1e-6
    return render_gray(np.clip(density / scale, 0.0, 1.0))


def simulate_bw_stages(scene_srgb: Array, settings: BWFilmSettings) -> dict[str, Array]:
    """Run the full B&W pipeline and return displayable images for each stage."""
    stages: dict[str, Array] = {}
    stages["00_input"] = np.clip(scene_srgb, 0.0, 1.0)

    base_bw = base_bw_conversion(scene_srgb, settings)
    stages["01_base_bw_conversion"] = render_gray(base_bw)

    exposure = expose_emulsion(scene_srgb, settings)
    stages["02_panchromatic_emulsion_exposure"] = render_exposure_debug(exposure)

    latent = form_latent_image(exposure, settings)
    stages["03_latent_image_probability"] = render_gray(latent)

    silver = develop_silver(latent, settings)
    stages["04_developed_metallic_silver_density"] = render_density_debug(silver)

    fixed_silver = fix_and_wash(silver, settings)
    stages["05_fixed_washed_silver_negative_density"] = render_density_debug(fixed_silver)

    negative = silver_to_negative_transmission(fixed_silver, settings)
    stages["06_bw_negative_transmission"] = render_gray(negative)

    negative_density = -np.log10(np.clip(negative, 1e-6, 1.0))
    stages["07_negative_density_debug"] = render_density_debug(negative_density)

    film_positive_no_grain = scan_negative_to_positive(negative, settings)
    stages["08_scanned_positive_no_final_grain"] = render_gray(film_positive_no_grain)

    film_positive_gray = add_visible_print_grain(film_positive_no_grain, settings)
    stages["09_film_positive_with_print_grain"] = render_gray(film_positive_gray)

    strength = np.clip(settings.effect_strength, 0.0, 1.0)
    blended_gray = base_bw * (1.0 - strength) + film_positive_gray * strength
    blended_gray = np.clip(blended_gray, 0.0, 1.0)
    stages["10_blended_with_base_bw"] = render_gray(blended_gray)

    final_gray = add_visible_print_grain(blended_gray, replace(settings, grain_strength=settings.grain_strength * 0.45))
    final_rgb = apply_tone(final_gray, settings)
    stages["11_final_output"] = final_rgb

    return stages


def save_all_stages(
    stages: dict[str, Array],
    output_path: str | Path,
    stages_dir: str | Path | None,
    quality: int = 95,
) -> None:
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


def simulate_bw(scene_srgb: Array, settings: BWFilmSettings, output_stage: OutputStage = "positive") -> Array:
    stages = simulate_bw_stages(scene_srgb, settings)

    if output_stage == "negative":
        return stages["06_bw_negative_transmission"]
    if output_stage == "silver":
        return stages["05_fixed_washed_silver_negative_density"]
    if output_stage == "latent":
        return stages["03_latent_image_probability"]
    if output_stage == "film_only":
        return stages["09_film_positive_with_print_grain"]
    if output_stage == "base_bw":
        return stages["01_base_bw_conversion"]
    return stages["11_final_output"]


# -----------------------------
# CLI
# -----------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="JPEG-friendly physically-inspired black-and-white film simulator")
    p.add_argument("input", help="Input image path")
    p.add_argument("output", nargs="?", default=None, help="Output image path. Default: <input_stem>_bw.jpg")
    p.add_argument("--preset", choices=sorted(PRESETS.keys()), default="neutral")
    p.add_argument(
        "--output-stage",
        choices=["positive", "negative", "silver", "latent", "film_only", "base_bw"],
        default="positive",
    )
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
    p.add_argument("--clump-size", type=float, default=None, help="Large grain clump size in pixels")
    p.add_argument("--crystal-density", type=float, default=None, help="Higher = finer/cleaner grain")
    p.add_argument("--halation", type=float, default=None)
    p.add_argument("--halation-radius", type=float, default=None)
    p.add_argument("--scan-contrast", type=float, default=None)
    p.add_argument("--scan-exposure", type=float, default=None)
    p.add_argument("--effect-strength", type=float, default=None, help="0 = normal B&W conversion, 1 = full film simulation")
    p.add_argument("--tone-strength", type=float, default=None)
    p.add_argument("--tone", choices=["neutral", "warm", "selenium"], default=None)
    p.add_argument("--seed", type=int, default=None)

    # B&W filter controls.
    p.add_argument("--red-filter", action="store_true", help="Simulate a red filter by changing spectral sensitivity")
    p.add_argument("--yellow-filter", action="store_true", help="Simulate a yellow filter by changing spectral sensitivity")
    p.add_argument("--blue-filter", action="store_true", help="Simulate a blue filter by changing spectral sensitivity")

    return p


def apply_cli_overrides(settings: BWFilmSettings, args: argparse.Namespace) -> BWFilmSettings:
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
        "clump_size": "clump_size_px",
        "crystal_density": "crystal_density",
        "halation": "halation_strength",
        "halation_radius": "halation_radius_px",
        "scan_contrast": "scan_contrast",
        "scan_exposure": "scan_exposure",
        "effect_strength": "effect_strength",
        "tone_strength": "tone_strength",
        "tone": "tone",
        "seed": "seed",
    }
    for arg_name, setting_name in mapping.items():
        value = getattr(args, arg_name)
        if value is not None:
            changes[setting_name] = value

    # Filter overrides. Last specified wins if user passes more than one.
    if args.red_filter:
        changes["spectral_sensitivity"] = (0.55, 0.35, 0.10)
    if args.yellow_filter:
        changes["spectral_sensitivity"] = (0.42, 0.48, 0.10)
    if args.blue_filter:
        changes["spectral_sensitivity"] = (0.10, 0.30, 0.60)

    return replace(settings, **changes)


def default_output_path(input_path: str | Path) -> str:
    """Return <input folder>/<input stem>_bw.jpg."""
    in_path = Path(input_path)
    return str(in_path.with_name(f"{in_path.stem}_bw.jpg"))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.output is None:
        args.output = default_output_path(args.input)

    settings = apply_cli_overrides(PRESETS[args.preset], args)
    scene = load_image(args.input, max_size=args.max_size)

    if args.save_stages:
        stages = simulate_bw_stages(scene, settings)
        save_all_stages(stages, args.output, args.stages_dir, quality=args.quality)
        result = simulate_bw(scene, settings, output_stage=args.output_stage)
    else:
        result = simulate_bw(scene, settings, output_stage=args.output_stage)

    save_image(result, args.output, quality=args.quality)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
