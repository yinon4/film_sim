# Film Lab

Browser-first film simulation playground built with `Vite`, `React`, `TypeScript`, `Tailwind CSS`, and a worker-based CPU image pipeline.

## What is here

- A routed art-tool UI with a guided workflow:
  - intro
  - film
  - camera
  - settings
  - expose
  - develop
  - final
- A Web Worker that:
  - decodes uploaded images off the main thread
  - keeps the UI responsive on CPU-only machines
  - renders proxy previews for interaction
  - renders larger final exports on demand
- Existing Python scripts remain in the root as the reference simulator:
  - `film_lab.py`
  - `film_simulator.py`
  - `film_simulator_bw_full.py`

## Why this stack

- `React + React Router`: good stateful UI and natural browser back/forward behavior.
- `Vite`: small, fast dev setup.
- `Tailwind`: quick iteration with a strong custom visual direction.
- `Web Worker + OffscreenCanvas`: the app stays usable without a GPU.

## Current simulation model

The browser render path is intentionally physically-inspired, not physically literal.

It currently approximates:

- stacked exposures
- film response curves
- halation
- grain
- vignette
- warmth / saturation bias
- development fog and push / pull effects

This keeps previews fast enough on CPU while preserving the creative feel of a film lab.

## Supported image flow today

- Import:
  - JPEG
  - PNG
  - WebP
  - TIFF
- Export:
  - PNG
  - JPEG

## Relationship to the Python code

The Python files are still useful and should be treated as the look-development lab.

Use them for:

- validating film-stock presets
- comparing tone and grain behavior
- prototyping stronger chemistry ideas before porting them to the browser

The web app should remain the primary user-facing product.

## Next steps

1. Port preset logic from the Python scripts into structured JSON or TS data.
2. Make exposure weights affect the worker render path directly.
3. Add crop and framing controls.
4. Add stage previews:
   - latent
   - negative
   - developed
   - final scan
5. Add project save/load files instead of only local storage persistence.
6. Add optional higher-quality offline rendering via Python if needed later.
