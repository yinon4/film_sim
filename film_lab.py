#!/usr/bin/env python3
"""
film_lab.py

Combined color + black-and-white photographic film simulator.

Install:
    pip install numpy pillow

Basic use:
    python film_lab.py input.jpg
    python film_lab.py input.jpg --mode bw
    python film_lab.py input.jpg --mode color --preset portraish
    python film_lab.py input.jpg --save-stages

Default output:
    color -> input_film.jpg
    bw    -> input_bw.jpg

Design goal:
    JPEG/PNG/TIFF-friendly. The default look is subtle, because normal digital
    images are already processed. Increase --effect, --grain, or use stronger
    presets for a more obvious film look.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageFilter, ImageOps

Array = np.ndarray
Mode = Literal["color", "bw"]
ColorStage = Literal["positive", "negative", "dye_density", "silver", "film_only"]
BWStage = Literal["positive", "negative", "silver", "latent", "film_only", "base_bw"]


# -----------------------------
# Utility math and IO
# -----------------------------

def srgb_to_linear(x: Array) -> Array:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: Array) -> Array:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * (x ** (1 / 2.4)) - 0.055)


def sigmoid(x: Array, midpoint: float, slope: float) -> Array:
    return 1.0 / (1.0 + np.exp(-slope * (x - midpoint)))


def soft_clip(x: Array, shoulder: float = 0.85, strength: float = 2.0) -> Array:
    x = np.asarray(x)
    below = x <= shoulder
    y = np.empty_like(x)
    y[below] = x[below]
    y[~below] = shoulder + (1.0 - shoulder) * (1.0 - np.exp(-strength * (x[~below] - shoulder)))
    return np.clip(y, 0.0, 1.0)


def normalize_noise(x: Array) -> Array:
    x = x.astype(np.float32)
    return (x - x.mean()) / (x.std() + 1e-6)


def blurred_noise(shape: tuple[int, int, int], rng: np.random.Generator, radius: float) -> Array:
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
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        img.save(path, quality=quality, subsampling=0, optimize=True)
    else:
        img.save(path)


def render_layer_image(layer_data: Array) -> Array:
    arr = np.asarray(layer_data, dtype=np.float32)
    flat = arr.reshape(-1, arr.shape[-1])
    lo = np.percentile(flat, 0.1, axis=0)
    hi = np.percentile(flat, 99.9, axis=0)
    return np.clip((arr - lo) / (hi - lo + 1e-6), 0.0, 1.0)


def save_all_stages(stages: dict[str, Array], output_path: str | Path, stages_dir: str | Path | None, quality: int = 95) -> None:
    output_path = Path(output_path)
    if stages_dir is None:
        base = output_path.with_suffix("")
        folder = base.parent / f"{base.name}_stages"
    else:
        folder = Path(stages_dir)
    folder.mkdir(parents=True, exist_ok=True)
    for name, image in stages.items():
        save_image(image, folder / f"{name}.jpg", quality=quality)


# -----------------------------
# Color film settings and presets
# -----------------------------

@dataclass(frozen=True)
class ColorSettings:
    iso: float = 400.0
    exposure_ev: float = 0.0
    sensitivity_matrix: tuple[tuple[float, float, float], ...] = (
        (1.00, 0.045, 0.018),
        (0.035, 1.00, 0.040),
        (0.018, 0.055, 1.00),
    )
    layer_ev_bias: tuple[float, float, float] = (0.0, 0.0, 0.0)
    crystal_density: float = 26000.0
    photon_scale: float = 10.0
    latent_threshold: float = 0.50
    latent_softness: float = 5.0
    developer_activity: float = 0.72
    development_time: float = 1.0
    contrast: float = 0.68
    shoulder: float = 0.70
    toe: float = 0.012
    max_dye_density: tuple[float, float, float] = (0.76, 0.72, 0.68)
    dye_gamma: tuple[float, float, float] = (0.86, 0.86, 0.86)
    dye_contamination: tuple[tuple[float, float, float], ...] = (
        (1.00, 0.040, 0.018),
        (0.035, 1.00, 0.025),
        (0.018, 0.045, 1.00),
    )
    orange_mask_rgb_density: tuple[float, float, float] = (0.035, 0.090, 0.160)
    base_fog_density: float = 0.012
    grain_strength: float = 0.34
    grain_size_px: float = 0.85
    micro_grain_size_px: float = 0.18
    clump_size_px: float = 1.10
    dye_cloud_size_px: float = 0.75
    dye_cloud_blur_px: float = 0.28
    chroma_grain: float = 0.22
    density_grain: float = 0.52
    halation_strength: float = 0.004
    halation_radius_px: float = 7.0
    scan_exposure: float = 1.0
    scan_contrast: float = 0.985
    scan_saturation: float = 0.985
    scan_temperature: float = 0.0
    black_point: float = 0.0
    white_point: float = 1.0
    effect_strength: float = 0.38
    seed: int = 1


COLOR_PRESETS: dict[str, ColorSettings] = {
    "neutral": ColorSettings(),
    "portraish": ColorSettings(
        developer_activity=0.70, contrast=0.64, shoulder=0.68,
        max_dye_density=(0.72, 0.68, 0.62), orange_mask_rgb_density=(0.040, 0.105, 0.180),
        grain_strength=0.30, grain_size_px=0.78, clump_size_px=1.0, dye_cloud_size_px=0.80,
        scan_saturation=0.96, scan_temperature=0.10, effect_strength=0.36,
    ),
    "ektarish": ColorSettings(
        developer_activity=0.76, contrast=0.76, shoulder=0.76,
        max_dye_density=(0.84, 0.80, 0.74), grain_strength=0.22,
        grain_size_px=0.55, clump_size_px=0.75, dye_cloud_size_px=0.55,
        scan_saturation=1.07, effect_strength=0.42,
    ),
    "cinema": ColorSettings(
        developer_activity=0.68, contrast=0.60, shoulder=0.64,
        max_dye_density=(0.70, 0.66, 0.62), orange_mask_rgb_density=(0.030, 0.080, 0.145),
        grain_strength=0.38, grain_size_px=0.95, clump_size_px=1.25, dye_cloud_size_px=1.00,
        halation_strength=0.020, halation_radius_px=13.0,
        scan_saturation=0.94, scan_contrast=0.96, effect_strength=0.40,
    ),
    "slideish": ColorSettings(
        developer_activity=0.84, contrast=0.92, shoulder=0.88,
        max_dye_density=(0.95, 0.92, 0.88), orange_mask_rgb_density=(0.0, 0.0, 0.0),
        base_fog_density=0.006, grain_strength=0.20, grain_size_px=0.45,
        clump_size_px=0.60, dye_cloud_size_px=0.45,
        scan_saturation=1.16, scan_contrast=1.04, effect_strength=0.48,
    ),
}


# -----------------------------
# B&W film settings and presets
# -----------------------------

@dataclass(frozen=True)
class BWSettings:
    iso: float = 400.0
    exposure_ev: float = 0.0
    spectral_sensitivity: tuple[float, float, float] = (0.28, 0.57, 0.15)
    crystal_density: float = 24000.0
    photon_scale: float = 10.0
    latent_threshold: float = 0.50
    latent_softness: float = 5.2
    developer_activity: float = 0.76
    development_time: float = 1.0
    contrast: float = 0.78
    shoulder: float = 0.74
    toe: float = 0.014
    max_silver_density: float = 0.90
    silver_gamma: float = 0.88
    base_fog_density: float = 0.020
    grain_strength: float = 0.34
    grain_size_px: float = 0.85
    micro_grain_size_px: float = 0.18
    clump_size_px: float = 1.10
    density_grain: float = 0.62
    halation_strength: float = 0.003
    halation_radius_px: float = 7.0
    scan_exposure: float = 1.0
    scan_contrast: float = 0.99
    print_gamma: float = 1.0
    black_point: float = 0.0
    white_point: float = 1.0
    tone: Literal["neutral", "warm", "selenium"] = "neutral"
    tone_strength: float = 0.0
    effect_strength: float = 0.42
    seed: int = 1


BW_PRESETS: dict[str, BWSettings] = {
    "neutral": BWSettings(),
    "hp5": BWSettings(
        spectral_sensitivity=(0.29, 0.56, 0.15), developer_activity=0.74,
        contrast=0.72, shoulder=0.70, max_silver_density=0.86,
        grain_strength=0.42, grain_size_px=1.00, clump_size_px=1.25,
        scan_contrast=0.97, effect_strength=0.46,
    ),
    "tri-x": BWSettings(
        spectral_sensitivity=(0.30, 0.55, 0.15), developer_activity=0.84,
        contrast=0.92, shoulder=0.82, max_silver_density=1.02,
        grain_strength=0.48, grain_size_px=0.95, clump_size_px=1.10,
        scan_contrast=1.05, effect_strength=0.52,
    ),
    "fine": BWSettings(
        iso=100.0, crystal_density=42000.0, photon_scale=11.0,
        developer_activity=0.72, contrast=0.76, max_silver_density=0.82,
        grain_strength=0.18, grain_size_px=0.45, micro_grain_size_px=0.12,
        clump_size_px=0.65, effect_strength=0.38,
    ),
    "pushed": BWSettings(
        iso=1600.0, developer_activity=0.98, development_time=1.15,
        contrast=1.08, shoulder=0.86, max_silver_density=1.12,
        grain_strength=0.70, grain_size_px=1.35, clump_size_px=1.70,
        scan_contrast=1.08, effect_strength=0.62,
    ),
    "warm-paper": BWSettings(
        developer_activity=0.74, contrast=0.74, grain_strength=0.30,
        tone="warm", tone_strength=0.28, effect_strength=0.44,
    ),
}


# -----------------------------
# Color process
# -----------------------------

def color_expose_layers(scene_srgb: Array, s: ColorSettings) -> Array:
    scene_linear = srgb_to_linear(scene_srgb)
    if s.halation_strength > 0:
        lum = 0.2126 * scene_linear[..., 0] + 0.7152 * scene_linear[..., 1] + 0.0722 * scene_linear[..., 2]
        highlights = np.clip((lum - 0.72) / 0.28, 0.0, 1.0) ** 2
        h_img = Image.fromarray(np.uint8(highlights * 255.0)).filter(ImageFilter.GaussianBlur(radius=s.halation_radius_px))
        halo = np.asarray(h_img).astype(np.float32) / 255.0
        scene_linear = scene_linear.copy()
        scene_linear[..., 0] += s.halation_strength * halo
        scene_linear[..., 1] += s.halation_strength * 0.32 * halo
    matrix = np.array(s.sensitivity_matrix, dtype=np.float32)
    exposures = np.tensordot(scene_linear, matrix.T, axes=([2], [0]))
    iso_factor = s.iso / 400.0
    ev_factor = 2.0 ** s.exposure_ev
    layer_bias = np.array([2.0 ** b for b in s.layer_ev_bias], dtype=np.float32)
    return np.clip(exposures * iso_factor * ev_factor * layer_bias, 0.0, None)


def make_color_grain(shape: tuple[int, int, int], s: ColorSettings, rng: np.random.Generator) -> Array:
    h, w, _ = shape
    shared = blurred_noise((h, w, 1), rng, s.clump_size_px)
    shared = np.repeat(shared, 3, axis=2)
    main = blurred_noise((h, w, 3), rng, s.grain_size_px)
    micro = blurred_noise((h, w, 3), rng, s.micro_grain_size_px)
    dye = blurred_noise((h, w, 3), rng, s.dye_cloud_size_px)
    return normalize_noise((1.0 - s.chroma_grain) * shared + s.chroma_grain * (0.55 * main + 0.45 * dye) + 0.22 * micro)


def color_form_latent(exposures: Array, s: ColorSettings) -> Array:
    rng = np.random.default_rng(s.seed)
    activation = 1.0 - np.exp(-s.photon_scale * exposures / max(s.crystal_density / 1000.0, 1e-6))
    grain = make_color_grain(exposures.shape, s, rng)
    exposure_weight = np.clip(4.0 * activation * (1.0 - activation), 0.0, 1.0)
    exposure_weight = 0.25 + 0.75 * exposure_weight
    noise_scale = s.grain_strength / np.sqrt(max(s.crystal_density / 1000.0, 1e-6))
    latent = sigmoid(activation + noise_scale * 0.65 * grain * exposure_weight, s.latent_threshold, s.latent_softness)
    shot_sigma = s.grain_strength * 0.012 / np.sqrt(max(s.crystal_density / 1000.0, 1e-6))
    latent += rng.normal(0.0, shot_sigma, latent.shape).astype(np.float32)
    return np.clip(latent, 0.0, 1.0)


def color_develop_silver(latent: Array, s: ColorSettings) -> Array:
    x = latent * s.developer_activity * s.development_time
    x = np.clip((x - s.toe) / max(1.0 - s.toe, 1e-6), 0.0, 1.0)
    x = x ** (1.0 / max(s.contrast, 1e-6))
    return np.clip(soft_clip(x, shoulder=s.shoulder, strength=2.4), 0.0, 1.0)


def color_form_dyes(silver: Array, s: ColorSettings) -> Array:
    rng = np.random.default_rng(s.seed + 1000)
    max_density = np.array(s.max_dye_density, dtype=np.float32)
    gamma = np.array(s.dye_gamma, dtype=np.float32)
    base = max_density * np.clip(silver, 0.0, 1.0) ** gamma
    cloud = make_color_grain(base.shape, s, rng)
    density_weight = np.clip(base / (max_density + 1e-6), 0.0, 1.0)
    midtone_weight = np.sqrt(np.clip(density_weight * (1.0 - 0.35 * density_weight), 0.0, 1.0))
    dyes = np.clip(base * (1.0 + s.grain_strength * s.density_grain * cloud * midtone_weight), 0.0, None)
    if s.dye_cloud_blur_px > 0:
        blurred = np.empty_like(dyes)
        for c in range(3):
            scale = max(float(max_density[c]), 1e-6)
            plane = np.clip(dyes[..., c] / scale, 0.0, 1.0)
            img = Image.fromarray(np.uint8(plane * 255.0)).filter(ImageFilter.GaussianBlur(radius=s.dye_cloud_blur_px))
            blurred[..., c] = (np.asarray(img).astype(np.float32) / 255.0) * scale
        dyes = blurred
    return np.clip(dyes, 0.0, None)


def color_negative_transmission(dyes: Array, s: ColorSettings) -> Array:
    contamination = np.array(s.dye_contamination, dtype=np.float32)
    rgb_density = np.tensordot(dyes, contamination, axes=([2], [0]))
    rgb_density += np.array(s.orange_mask_rgb_density, dtype=np.float32)
    rgb_density += s.base_fog_density
    return np.clip(10.0 ** (-rgb_density), 0.0, 1.0)


def color_scan_negative(negative_rgb: Array, s: ColorSettings) -> Array:
    density = -np.log10(np.clip(negative_rgb, 1e-6, 1.0))
    mask = np.array(s.orange_mask_rgb_density, dtype=np.float32) + s.base_fog_density
    density = np.clip(density - mask, 0.0, None)
    lo = np.percentile(density.reshape(-1, 3), 0.02, axis=0)
    hi = np.percentile(density.reshape(-1, 3), 99.98, axis=0)
    pos = np.clip((density - lo) / (hi - lo + 1e-6), 0.0, 1.0)
    pos = np.clip(pos * s.scan_exposure, 0.0, 1.0)
    pos = np.clip((pos - 0.5) * s.scan_contrast + 0.5, 0.0, 1.0)
    pos = np.clip((pos - s.black_point) / max(s.white_point - s.black_point, 1e-6), 0.0, 1.0)
    lum = 0.2126 * pos[..., 0:1] + 0.7152 * pos[..., 1:2] + 0.0722 * pos[..., 2:3]
    pos = lum + s.scan_saturation * (pos - lum)
    pos[..., 0] *= 1.0 + 0.08 * s.scan_temperature
    pos[..., 2] *= 1.0 - 0.08 * s.scan_temperature
    return np.clip(linear_to_srgb(pos), 0.0, 1.0)


def color_add_print_grain(img_srgb: Array, s: ColorSettings, scale: float = 1.0) -> Array:
    if s.grain_strength <= 0:
        return img_srgb
    rng = np.random.default_rng(s.seed + 2000)
    h, w = img_srgb.shape[:2]
    coarse = blurred_noise((h, w, 1), rng, s.clump_size_px)
    fine = blurred_noise((h, w, 1), rng, s.micro_grain_size_px)
    layer = blurred_noise((h, w, 3), rng, s.dye_cloud_size_px)
    lum_grain = normalize_noise(0.85 * coarse + 0.35 * fine)
    grain = lum_grain + layer * s.chroma_grain * 0.30
    linear = srgb_to_linear(img_srgb)
    lum = 0.2126 * linear[..., 0:1] + 0.7152 * linear[..., 1:2] + 0.0722 * linear[..., 2:3]
    visibility = np.clip(1.0 - 0.65 * lum, 0.25, 1.0)
    amount = 0.055 * s.grain_strength * scale
    return np.clip(linear_to_srgb(linear * (1.0 + amount * grain * visibility)), 0.0, 1.0)


def color_render_dye_density(dyes: Array) -> Array:
    maxv = np.percentile(dyes, 99.5) + 1e-6
    cmy = np.clip(dyes / maxv, 0.0, 1.0)
    return np.clip(1.0 - np.stack([cmy[..., 0], cmy[..., 1], cmy[..., 2]], axis=-1), 0.0, 1.0)


def color_render_silver(silver: Array) -> Array:
    gray = np.mean(silver, axis=2)
    gray = gray / (np.percentile(gray, 99.5) + 1e-6)
    return render_gray(1.0 - np.clip(gray, 0.0, 1.0))


def color_stages(scene_srgb: Array, s: ColorSettings) -> dict[str, Array]:
    stages: dict[str, Array] = {"00_input": np.clip(scene_srgb, 0, 1)}
    exposures = color_expose_layers(scene_srgb, s)
    stages["01_layer_exposures_rgb_sensitive"] = render_layer_image(exposures)
    latent = color_form_latent(exposures, s)
    stages["02_latent_image_probability"] = render_layer_image(latent)
    silver = color_develop_silver(latent, s)
    stages["03_developed_silver_before_bleach"] = color_render_silver(silver)
    dyes = color_form_dyes(silver, s)
    stages["04_cmy_dye_density"] = color_render_dye_density(dyes)
    removed_silver = np.zeros_like(silver)
    stages["05_bleached_silver_removed"] = color_render_silver(removed_silver)
    stages["06_fixed_cmy_dye_density"] = color_render_dye_density(dyes)
    negative = color_negative_transmission(dyes, s)
    stages["07_orange_masked_negative_transmission"] = negative
    density = -np.log10(np.clip(negative, 1e-6, 1.0))
    stages["08_negative_density_debug"] = np.clip(density / (np.percentile(density, 99.8) + 1e-6), 0.0, 1.0)
    film_no_grain = color_scan_negative(negative, s)
    stages["09_scanned_positive_no_final_grain"] = film_no_grain
    film = color_add_print_grain(film_no_grain, s, scale=1.0)
    stages["10_film_positive_with_print_grain"] = film
    strength = np.clip(s.effect_strength, 0.0, 1.0)
    blended = np.clip(scene_srgb * (1.0 - strength) + film * strength, 0.0, 1.0)
    stages["11_blended_with_original"] = blended
    stages["12_final_output"] = color_add_print_grain(blended, replace(s, grain_strength=s.grain_strength * 0.55), scale=1.0)
    return stages


# -----------------------------
# B&W process
# -----------------------------

def bw_base_conversion(scene_srgb: Array, s: BWSettings) -> Array:
    linear = srgb_to_linear(scene_srgb)
    weights = np.array(s.spectral_sensitivity, dtype=np.float32)
    weights /= weights.sum() + 1e-6
    gray = np.tensordot(linear, weights, axes=([2], [0]))
    return np.clip(linear_to_srgb(gray), 0.0, 1.0)


def bw_expose(scene_srgb: Array, s: BWSettings) -> Array:
    linear = srgb_to_linear(scene_srgb)
    if s.halation_strength > 0:
        lum = 0.2126 * linear[..., 0] + 0.7152 * linear[..., 1] + 0.0722 * linear[..., 2]
        highlights = np.clip((lum - 0.74) / 0.26, 0.0, 1.0) ** 2
        h_img = Image.fromarray(np.uint8(highlights * 255.0)).filter(ImageFilter.GaussianBlur(radius=s.halation_radius_px))
        halo = np.asarray(h_img).astype(np.float32) / 255.0
        linear = linear.copy() + s.halation_strength * halo[..., None]
    weights = np.array(s.spectral_sensitivity, dtype=np.float32)
    weights /= weights.sum() + 1e-6
    exposure = np.tensordot(linear, weights, axes=([2], [0]))
    return np.clip(exposure * (s.iso / 400.0) * (2.0 ** s.exposure_ev), 0.0, None)


def make_bw_grain(shape_hw: tuple[int, int], s: BWSettings, rng: np.random.Generator) -> Array:
    h, w = shape_hw
    clumps = blurred_noise((h, w, 1), rng, s.clump_size_px)[..., 0]
    main = blurred_noise((h, w, 1), rng, s.grain_size_px)[..., 0]
    micro = blurred_noise((h, w, 1), rng, s.micro_grain_size_px)[..., 0]
    return normalize_noise(0.55 * clumps + 0.75 * main + 0.22 * micro)


def bw_form_latent(exposure: Array, s: BWSettings) -> Array:
    rng = np.random.default_rng(s.seed)
    activation = 1.0 - np.exp(-s.photon_scale * exposure / max(s.crystal_density / 1000.0, 1e-6))
    grain = make_bw_grain(exposure.shape, s, rng)
    exposure_weight = np.clip(4.0 * activation * (1.0 - activation), 0.0, 1.0)
    exposure_weight = 0.22 + 0.78 * exposure_weight
    noise_scale = s.grain_strength / np.sqrt(max(s.crystal_density / 1000.0, 1e-6))
    latent = sigmoid(activation + noise_scale * 0.78 * grain * exposure_weight, s.latent_threshold, s.latent_softness)
    shot_sigma = s.grain_strength * 0.014 / np.sqrt(max(s.crystal_density / 1000.0, 1e-6))
    latent += rng.normal(0.0, shot_sigma, latent.shape).astype(np.float32)
    return np.clip(latent, 0.0, 1.0)


def bw_develop_silver(latent: Array, s: BWSettings) -> Array:
    x = latent * s.developer_activity * s.development_time
    x = np.clip((x - s.toe) / max(1.0 - s.toe, 1e-6), 0.0, 1.0)
    x = x ** (1.0 / max(s.contrast, 1e-6))
    x = soft_clip(x, shoulder=s.shoulder, strength=2.4)
    return np.clip(s.max_silver_density * (x ** s.silver_gamma), 0.0, None)


def bw_negative_transmission(silver: Array, s: BWSettings) -> Array:
    return np.clip(10.0 ** (-(silver + s.base_fog_density)), 0.0, 1.0)


def bw_scan_negative(negative: Array, s: BWSettings) -> Array:
    density = -np.log10(np.clip(negative, 1e-6, 1.0))
    density = np.clip(density - s.base_fog_density, 0.0, None)
    lo = np.percentile(density, 0.02)
    hi = np.percentile(density, 99.98)
    pos = np.clip((density - lo) / (hi - lo + 1e-6), 0.0, 1.0)
    pos = np.clip(pos * s.scan_exposure, 0.0, 1.0)
    pos = np.clip((pos - 0.5) * s.scan_contrast + 0.5, 0.0, 1.0)
    pos = np.clip((pos - s.black_point) / max(s.white_point - s.black_point, 1e-6), 0.0, 1.0)
    if s.print_gamma != 1.0:
        pos = pos ** (1.0 / max(s.print_gamma, 1e-6))
    return np.clip(linear_to_srgb(pos), 0.0, 1.0)


def bw_add_print_grain(gray_srgb: Array, s: BWSettings, scale: float = 1.0) -> Array:
    if s.grain_strength <= 0:
        return gray_srgb
    rng = np.random.default_rng(s.seed + 2000)
    h, w = gray_srgb.shape[:2]
    clump = blurred_noise((h, w, 1), rng, s.clump_size_px)[..., 0]
    coarse = blurred_noise((h, w, 1), rng, s.grain_size_px)[..., 0]
    fine = blurred_noise((h, w, 1), rng, s.micro_grain_size_px)[..., 0]
    grain = normalize_noise(0.60 * clump + 0.75 * coarse + 0.30 * fine)
    linear = srgb_to_linear(gray_srgb)
    visibility = np.clip(1.0 - 0.65 * linear, 0.25, 1.0)
    amount = 0.070 * s.grain_strength * scale
    return np.clip(linear_to_srgb(linear * (1.0 + amount * grain * visibility)), 0.0, 1.0)


def bw_apply_tone(gray_srgb: Array, s: BWSettings) -> Array:
    gray = np.clip(gray_srgb, 0.0, 1.0)
    base = render_gray(gray)
    strength = np.clip(s.tone_strength, 0.0, 1.0)
    if s.tone == "neutral" or strength <= 0:
        return base
    if s.tone == "warm":
        tone_rgb = np.array([1.055, 1.015, 0.955], dtype=np.float32)
        return np.clip(base * (1.0 + strength * (tone_rgb - 1.0)), 0.0, 1.0)
    if s.tone == "selenium":
        shadow = np.clip(1.0 - gray, 0.0, 1.0)[..., None]
        tone_rgb = np.array([0.970, 0.990, 1.045], dtype=np.float32)
        return np.clip(base * (1.0 + strength * shadow * (tone_rgb - 1.0)), 0.0, 1.0)
    return base


def bw_render_exposure(exposure: Array) -> Array:
    lo = np.percentile(exposure, 0.1)
    hi = np.percentile(exposure, 99.9)
    return render_gray(np.clip((exposure - lo) / (hi - lo + 1e-6), 0.0, 1.0))


def bw_render_density(density: Array) -> Array:
    return render_gray(np.clip(density / (np.percentile(density, 99.8) + 1e-6), 0.0, 1.0))


def bw_stages(scene_srgb: Array, s: BWSettings) -> dict[str, Array]:
    stages: dict[str, Array] = {"00_input": np.clip(scene_srgb, 0, 1)}
    base_bw = bw_base_conversion(scene_srgb, s)
    stages["01_base_bw_conversion"] = render_gray(base_bw)
    exposure = bw_expose(scene_srgb, s)
    stages["02_panchromatic_emulsion_exposure"] = bw_render_exposure(exposure)
    latent = bw_form_latent(exposure, s)
    stages["03_latent_image_probability"] = render_gray(latent)
    silver = bw_develop_silver(latent, s)
    stages["04_developed_metallic_silver_density"] = bw_render_density(silver)
    stages["05_fixed_washed_silver_negative_density"] = bw_render_density(silver)
    negative = bw_negative_transmission(silver, s)
    stages["06_bw_negative_transmission"] = render_gray(negative)
    negative_density = -np.log10(np.clip(negative, 1e-6, 1.0))
    stages["07_negative_density_debug"] = bw_render_density(negative_density)
    film_no_grain = bw_scan_negative(negative, s)
    stages["08_scanned_positive_no_final_grain"] = render_gray(film_no_grain)
    film = bw_add_print_grain(film_no_grain, s, scale=1.0)
    stages["09_film_positive_with_print_grain"] = render_gray(film)
    strength = np.clip(s.effect_strength, 0.0, 1.0)
    blended = np.clip(base_bw * (1.0 - strength) + film * strength, 0.0, 1.0)
    stages["10_blended_with_base_bw"] = render_gray(blended)
    final_gray = bw_add_print_grain(blended, replace(s, grain_strength=s.grain_strength * 0.45), scale=1.0)
    stages["11_final_output"] = bw_apply_tone(final_gray, s)
    return stages


# -----------------------------
# CLI and dispatch
# -----------------------------

def default_output_path(input_path: str | Path, mode: Mode) -> str:
    in_path = Path(input_path)
    suffix = "bw" if mode == "bw" else "film"
    return str(in_path.with_name(f"{in_path.stem}_{suffix}.jpg"))


def preset_names(mode: Mode) -> list[str]:
    return sorted(BW_PRESETS.keys() if mode == "bw" else COLOR_PRESETS.keys())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Combined JPEG-friendly color and black-and-white film simulator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Input image path")
    p.add_argument("output", nargs="?", default=None, help="Output path. Default: <input>_film.jpg or <input>_bw.jpg")
    p.add_argument("--mode", choices=["color", "bw"], default="color", help="Film process")
    p.add_argument("--preset", default="neutral", help="Preset. Use --list-presets to see choices")
    p.add_argument("--list-presets", action="store_true", help="List presets for both modes and exit")
    p.add_argument("--output-stage", default="positive", help="positive, film_only, negative, silver; color also dye_density; bw also latent/base_bw")
    p.add_argument("--max-size", type=int, default=None, help="Resize largest side before processing")
    p.add_argument("--quality", type=int, default=95, help="JPEG output quality")
    p.add_argument("--save-stages", action="store_true", help="Save every process stage")
    p.add_argument("--stages-dir", default=None, help="Folder for stage images")
    p.add_argument("--info", action="store_true", help="Print image/settings info")

    # Shared controls
    p.add_argument("--iso", type=float, default=None)
    p.add_argument("--exposure", type=float, default=None, help="Exposure compensation in EV/stops")
    p.add_argument("--contrast", type=float, default=None, help="Development contrast")
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
    p.add_argument("--effect", "--effect-strength", dest="effect_strength", type=float, default=None, help="0 = source-like, 1 = full simulation")
    p.add_argument("--seed", type=int, default=None)

    # Color-only controls
    p.add_argument("--saturation", type=float, default=None, help="Color mode scan saturation")
    p.add_argument("--temperature", type=float, default=None, help="Color mode scan temperature; negative=cooler, positive=warmer")
    p.add_argument("--dye-cloud-size", type=float, default=None, help="Color mode dye cloud size")
    p.add_argument("--chroma-grain", type=float, default=None, help="Color mode chroma grain amount")

    # B&W-only controls
    p.add_argument("--tone", choices=["neutral", "warm", "selenium"], default=None)
    p.add_argument("--tone-strength", type=float, default=None)
    p.add_argument("--red-filter", action="store_true")
    p.add_argument("--yellow-filter", action="store_true")
    p.add_argument("--blue-filter", action="store_true")
    return p


def apply_common_overrides(settings, args):
    changes = {}
    mapping = {
        "iso": "iso", "exposure": "exposure_ev", "contrast": "contrast",
        "developer_activity": "developer_activity", "development_time": "development_time",
        "grain": "grain_strength", "grain_size": "grain_size_px", "micro_grain_size": "micro_grain_size_px",
        "clump_size": "clump_size_px", "crystal_density": "crystal_density",
        "halation": "halation_strength", "halation_radius": "halation_radius_px",
        "scan_contrast": "scan_contrast", "scan_exposure": "scan_exposure",
        "effect_strength": "effect_strength", "seed": "seed",
    }
    for arg_name, setting_name in mapping.items():
        if hasattr(settings, setting_name):
            value = getattr(args, arg_name)
            if value is not None:
                changes[setting_name] = value
    return changes


def build_color_settings(args) -> ColorSettings:
    if args.preset not in COLOR_PRESETS:
        raise SystemExit(f"Unknown color preset '{args.preset}'. Choices: {', '.join(preset_names('color'))}")
    changes = apply_common_overrides(COLOR_PRESETS[args.preset], args)
    color_mapping = {
        "saturation": "scan_saturation",
        "temperature": "scan_temperature",
        "dye_cloud_size": "dye_cloud_size_px",
        "chroma_grain": "chroma_grain",
    }
    for arg_name, setting_name in color_mapping.items():
        value = getattr(args, arg_name)
        if value is not None:
            changes[setting_name] = value
    return replace(COLOR_PRESETS[args.preset], **changes)


def build_bw_settings(args) -> BWSettings:
    if args.preset not in BW_PRESETS:
        raise SystemExit(f"Unknown bw preset '{args.preset}'. Choices: {', '.join(preset_names('bw'))}")
    changes = apply_common_overrides(BW_PRESETS[args.preset], args)
    for arg_name, setting_name in {"tone": "tone", "tone_strength": "tone_strength"}.items():
        value = getattr(args, arg_name)
        if value is not None:
            changes[setting_name] = value
    if args.red_filter:
        changes["spectral_sensitivity"] = (0.55, 0.35, 0.10)
    if args.yellow_filter:
        changes["spectral_sensitivity"] = (0.42, 0.48, 0.10)
    if args.blue_filter:
        changes["spectral_sensitivity"] = (0.10, 0.30, 0.60)
    return replace(BW_PRESETS[args.preset], **changes)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.list_presets:
        print("Color presets:", ", ".join(preset_names("color")))
        print("B&W presets:  ", ", ".join(preset_names("bw")))
        return

    if args.output is None:
        args.output = default_output_path(args.input, args.mode)

    scene = load_image(args.input, max_size=args.max_size)

    if args.mode == "color":
        settings = build_color_settings(args)
        stages = color_stages(scene, settings)
        valid = {"positive", "negative", "dye_density", "silver", "film_only"}
        if args.output_stage not in valid:
            raise SystemExit(f"Invalid color --output-stage '{args.output_stage}'. Choices: {', '.join(sorted(valid))}")
        if args.output_stage == "negative":
            result = stages["07_orange_masked_negative_transmission"]
        elif args.output_stage == "dye_density":
            result = stages["06_fixed_cmy_dye_density"]
        elif args.output_stage == "silver":
            result = stages["03_developed_silver_before_bleach"]
        elif args.output_stage == "film_only":
            result = stages["10_film_positive_with_print_grain"]
        else:
            result = stages["12_final_output"]
    else:
        settings = build_bw_settings(args)
        stages = bw_stages(scene, settings)
        valid = {"positive", "negative", "silver", "latent", "film_only", "base_bw"}
        if args.output_stage not in valid:
            raise SystemExit(f"Invalid bw --output-stage '{args.output_stage}'. Choices: {', '.join(sorted(valid))}")
        if args.output_stage == "negative":
            result = stages["06_bw_negative_transmission"]
        elif args.output_stage == "silver":
            result = stages["05_fixed_washed_silver_negative_density"]
        elif args.output_stage == "latent":
            result = stages["03_latent_image_probability"]
        elif args.output_stage == "film_only":
            result = stages["09_film_positive_with_print_grain"]
        elif args.output_stage == "base_bw":
            result = stages["01_base_bw_conversion"]
        else:
            result = stages["11_final_output"]

    if args.save_stages:
        save_all_stages(stages, args.output, args.stages_dir, quality=args.quality)

    save_image(result, args.output, quality=args.quality)

    if args.info:
        print(f"Loaded image: {scene.shape[1]}x{scene.shape[0]}")
        print(f"Mode: {args.mode}")
        print(f"Preset: {args.preset}")
        print(f"Settings: {settings}")
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
