export type FilmKind = "color-negative" | "bw-negative" | "slide";

export type FilmPreset = {
  id: string;
  name: string;
  kind: FilmKind;
  description: string;
  iso: number;
  contrast: number;
  saturation: number;
  grain: number;
  halation: number;
  warmth: number;
};

export type CameraPreset = {
  id: string;
  name: string;
  format: string;
  character: string;
  formatWeight: number;
  edgeFalloff: number;
};

export type LensPreset = {
  id: string;
  name: string;
  focalLength: string;
  character: string;
  bloom: number;
  vignette: number;
  halationBias: number;
};

export const filmPresets: FilmPreset[] = [
  {
    id: "portra-400",
    name: "Portra 400-ish",
    kind: "color-negative",
    description: "Warm skin tones, soft shoulder, forgiving highlights.",
    iso: 400,
    contrast: 0.44,
    saturation: 0.9,
    grain: 0.32,
    halation: 0.16,
    warmth: 0.18,
  },
  {
    id: "gold-200",
    name: "Gold 200-ish",
    kind: "color-negative",
    description: "Cheap daylight warmth, denser grain, nostalgic yellows.",
    iso: 200,
    contrast: 0.48,
    saturation: 0.96,
    grain: 0.42,
    halation: 0.14,
    warmth: 0.24,
  },
  {
    id: "ultramax-400",
    name: "Ultramax 400-ish",
    kind: "color-negative",
    description: "Louder consumer color with stronger reds and grain.",
    iso: 400,
    contrast: 0.5,
    saturation: 1.02,
    grain: 0.4,
    halation: 0.18,
    warmth: 0.2,
  },
  {
    id: "vision-250d",
    name: "Vision 250D-ish",
    kind: "color-negative",
    description: "Cinematic latitude with a gentle pastel scan bias.",
    iso: 250,
    contrast: 0.38,
    saturation: 0.86,
    grain: 0.22,
    halation: 0.24,
    warmth: 0.1,
  },
  {
    id: "vision-500t",
    name: "Vision 500T-ish",
    kind: "color-negative",
    description: "Cool tungsten stock with bloomier highlights and softer color.",
    iso: 500,
    contrast: 0.36,
    saturation: 0.8,
    grain: 0.34,
    halation: 0.32,
    warmth: -0.14,
  },
  {
    id: "ektar-100",
    name: "Ektar 100-ish",
    kind: "color-negative",
    description: "Fine grain, punchy color, cleaner edges.",
    iso: 100,
    contrast: 0.62,
    saturation: 1.12,
    grain: 0.14,
    halation: 0.1,
    warmth: 0.02,
  },
  {
    id: "provia-100f",
    name: "Provia 100F-ish",
    kind: "slide",
    description: "Balanced slide stock with crisp color and tighter contrast.",
    iso: 100,
    contrast: 0.72,
    saturation: 1.08,
    grain: 0.16,
    halation: 0.12,
    warmth: -0.02,
  },
  {
    id: "velvia-50",
    name: "Velvia 50-ish",
    kind: "slide",
    description: "High saturation, deep contrast, landscape postcard energy.",
    iso: 50,
    contrast: 0.86,
    saturation: 1.26,
    grain: 0.12,
    halation: 0.1,
    warmth: -0.05,
  },
  {
    id: "trix-400",
    name: "Tri-X 400-ish",
    kind: "bw-negative",
    description: "Chunky grain, punchy mids, a classic darkroom mood.",
    iso: 400,
    contrast: 0.58,
    saturation: 0,
    grain: 0.54,
    halation: 0.08,
    warmth: -0.04,
  },
  {
    id: "hp5-400",
    name: "HP5 400-ish",
    kind: "bw-negative",
    description: "Softer black and white with broad latitude and classic texture.",
    iso: 400,
    contrast: 0.46,
    saturation: 0,
    grain: 0.48,
    halation: 0.07,
    warmth: 0,
  },
  {
    id: "delta-3200",
    name: "Delta 3200-ish",
    kind: "bw-negative",
    description: "Low-light grit, lifted fog, and fast-stock roughness.",
    iso: 3200,
    contrast: 0.52,
    saturation: 0,
    grain: 0.72,
    halation: 0.11,
    warmth: -0.02,
  },
];

export const cameraPresets: CameraPreset[] = [
  {
    id: "pentax-k1000",
    name: "Pentax K1000",
    format: "35mm",
    character: "Simple meter, honest handling, everyday diary energy.",
    formatWeight: 1,
    edgeFalloff: 0.1,
  },
  {
    id: "nikon-fm2",
    name: "Nikon FM2",
    format: "35mm",
    character: "Fast shutter, sturdy body, crisp street momentum.",
    formatWeight: 0.98,
    edgeFalloff: 0.08,
  },
  {
    id: "canon-ae1",
    name: "Canon AE-1",
    format: "35mm",
    character: "Consumer classic with a slightly brighter, softer feel.",
    formatWeight: 1,
    edgeFalloff: 0.11,
  },
  {
    id: "contax-g2",
    name: "Contax G2",
    format: "35mm",
    character: "Sharper, cleaner, lower falloff rangefinder look.",
    formatWeight: 0.96,
    edgeFalloff: 0.06,
  },
  {
    id: "mamiya-7",
    name: "Mamiya 7",
    format: "120",
    character: "Medium-format air, calmer perspective, luminous detail.",
    formatWeight: 0.82,
    edgeFalloff: 0.05,
  },
  {
    id: "hasselblad-500cm",
    name: "Hasselblad 500CM",
    format: "120",
    character: "Square medium format with denser center rendering.",
    formatWeight: 0.86,
    edgeFalloff: 0.06,
  },
  {
    id: "pentax-67",
    name: "Pentax 67",
    format: "120",
    character: "Big negative, heavier vignette potential, portrait weight.",
    formatWeight: 0.84,
    edgeFalloff: 0.08,
  },
  {
    id: "linhof-4x5",
    name: "Linhof 4x5",
    format: "Sheet film",
    character: "Deliberate pace, large negative poetry, sculpted depth.",
    formatWeight: 0.7,
    edgeFalloff: 0.03,
  },
];

export const lensPresets: LensPreset[] = [
  {
    id: "takumar-50",
    name: "Super-Takumar 50mm",
    focalLength: "50mm f/1.4",
    character: "Warm glass, slight bloom, intimate normal view.",
    bloom: 0.44,
    vignette: 0.1,
    halationBias: 0.11,
  },
  {
    id: "helios-44-2",
    name: "Helios 44-2",
    focalLength: "58mm f/2",
    character: "Swirl, flare, and imperfect edges when pushed.",
    bloom: 0.62,
    vignette: 0.16,
    halationBias: 0.18,
  },
  {
    id: "canon-fd-35",
    name: "Canon FD 35mm",
    focalLength: "35mm f/2",
    character: "Wide, lively, with moderate flare and street contrast.",
    bloom: 0.34,
    vignette: 0.12,
    halationBias: 0.08,
  },
  {
    id: "nikkor-105",
    name: "Nikkor 105mm",
    focalLength: "105mm f/2.5",
    character: "Portrait compression with restrained contrast.",
    bloom: 0.24,
    vignette: 0.07,
    halationBias: 0.06,
  },
  {
    id: "planar-80",
    name: "Zeiss Planar 80mm",
    focalLength: "80mm f/2.8",
    character: "Clean medium-format normal lens with lower bloom.",
    bloom: 0.2,
    vignette: 0.05,
    halationBias: 0.04,
  },
  {
    id: "mamiya-80",
    name: "Mamiya 80mm",
    focalLength: "80mm f/4",
    character: "Medium-format balance with a calm, open rendering.",
    bloom: 0.28,
    vignette: 0.08,
    halationBias: 0.05,
  },
  {
    id: "canon-50-ltm",
    name: "Canon 50mm LTM",
    focalLength: "50mm f/1.2",
    character: "Vintage glow with stronger bloom and soft highlight edges.",
    bloom: 0.58,
    vignette: 0.14,
    halationBias: 0.15,
  },
  {
    id: "schneider-150",
    name: "Schneider 150mm",
    focalLength: "150mm f/5.6",
    character: "Large-format coverage with low falloff and clean corners.",
    bloom: 0.16,
    vignette: 0.04,
    halationBias: 0.03,
  },
];

export const filmPresetMap = new Map(filmPresets.map((preset) => [preset.id, preset]));
export const cameraPresetMap = new Map(cameraPresets.map((preset) => [preset.id, preset]));
export const lensPresetMap = new Map(lensPresets.map((preset) => [preset.id, preset]));
