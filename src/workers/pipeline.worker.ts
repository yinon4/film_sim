/// <reference lib="webworker" />

import type {
  RenderRecipe,
  WorkerRequest,
  WorkerResponse,
} from "../lib/pipeline";

type StoredExposure = {
  bitmap: ImageBitmap;
  width: number;
  height: number;
};

const exposures = new Map<string, StoredExposure>();

const post = (message: WorkerResponse) => {
  self.postMessage(message);
};

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

const srgbToLinear = (value: number) => {
  const normalized = value / 255;
  if (normalized <= 0.04045) {
    return normalized / 12.92;
  }
  return ((normalized + 0.055) / 1.055) ** 2.4;
};

const linearToSrgb = (value: number) => {
  const clipped = clamp01(value);
  if (clipped <= 0.0031308) {
    return clipped * 12.92 * 255;
  }
  return (1.055 * clipped ** (1 / 2.4) - 0.055) * 255;
};

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const makeCanvas = (width: number, height: number) =>
  new OffscreenCanvas(width, height);

const drawScaled = (
  bitmap: ImageBitmap,
  width: number,
  height: number,
): ImageData => {
  const canvas = makeCanvas(width, height);
  const ctx = canvas.getContext("2d", {
    willReadFrequently: true,
  });
  if (!ctx) {
    throw new Error("2D canvas context is unavailable.");
  }
  ctx.drawImage(bitmap, 0, 0, width, height);
  return ctx.getImageData(0, 0, width, height);
};

const drawTransformed = (
  bitmap: ImageBitmap,
  width: number,
  height: number,
  offsetX: number,
  offsetY: number,
  rotation: number,
): ImageData => {
  const canvas = makeCanvas(width, height);
  const ctx = canvas.getContext("2d", {
    willReadFrequently: true,
  });
  if (!ctx) {
    throw new Error("2D canvas context is unavailable.");
  }
  ctx.translate(width / 2 + offsetX * width, height / 2 + offsetY * height);
  ctx.rotate((rotation * Math.PI) / 180);
  ctx.drawImage(bitmap, -width / 2, -height / 2, width, height);
  return ctx.getImageData(0, 0, width, height);
};

const gaussianBlur = (
  source: Float32Array,
  width: number,
  height: number,
  radius: number,
): Float32Array => {
  if (radius <= 0.2) {
    return source;
  }

  const sigma = Math.max(0.8, radius);
  const kernelRadius = Math.max(1, Math.floor(radius * 2));
  const kernelSize = kernelRadius * 2 + 1;
  const kernel = new Float32Array(kernelSize);
  let total = 0;

  for (let index = 0; index < kernelSize; index += 1) {
    const distance = index - kernelRadius;
    const value = Math.exp(-(distance * distance) / (2 * sigma * sigma));
    kernel[index] = value;
    total += value;
  }
  for (let index = 0; index < kernelSize; index += 1) {
    kernel[index] /= total;
  }

  const horizontal = new Float32Array(source.length);
  const output = new Float32Array(source.length);

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let sum = 0;
      for (let k = -kernelRadius; k <= kernelRadius; k += 1) {
        const sampleX = Math.min(width - 1, Math.max(0, x + k));
        sum += source[y * width + sampleX] * kernel[k + kernelRadius];
      }
      horizontal[y * width + x] = sum;
    }
  }

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let sum = 0;
      for (let k = -kernelRadius; k <= kernelRadius; k += 1) {
        const sampleY = Math.min(height - 1, Math.max(0, y + k));
        sum += horizontal[sampleY * width + x] * kernel[k + kernelRadius];
      }
      output[y * width + x] = sum;
    }
  }

  return output;
};

const hashNoise = (x: number, y: number, seed: number) => {
  const value = Math.sin(x * 12.9898 + y * 78.233 + seed * 0.1234) * 43758.5453;
  return value - Math.floor(value);
};

const addLightLeak = (
  output: Uint8ClampedArray,
  width: number,
  height: number,
  strength: number,
  seed: number,
) => {
  if (strength <= 0.001) {
    return;
  }
  const side = Math.floor(hashNoise(seed, seed * 0.5, seed) * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const pixel = y * width + x;
      const offset = pixel * 4;
      let edgeDistance = 0;
      if (side === 0) edgeDistance = x / Math.max(1, width - 1);
      if (side === 1) edgeDistance = 1 - x / Math.max(1, width - 1);
      if (side === 2) edgeDistance = y / Math.max(1, height - 1);
      if (side === 3) edgeDistance = 1 - y / Math.max(1, height - 1);
      const leak = Math.max(0, 1 - edgeDistance * 3.2) * strength;
      output[offset] = Math.min(255, output[offset] + leak * 155);
      output[offset + 1] = Math.min(255, output[offset + 1] + leak * 78);
      output[offset + 2] = Math.min(255, output[offset + 2] + leak * 22);
    }
  }
};

const addDustAndScratches = (
  output: Uint8ClampedArray,
  width: number,
  height: number,
  dust: number,
  scratches: number,
  seed: number,
) => {
  const dustCount = Math.round(dust * 120);
  for (let index = 0; index < dustCount; index += 1) {
    const cx = Math.floor(hashNoise(index, seed, seed + 11) * width);
    const cy = Math.floor(hashNoise(index, seed + 3, seed + 17) * height);
    const radius = 1 + Math.floor(hashNoise(index, seed + 7, seed + 19) * 3);
    for (let y = Math.max(0, cy - radius); y <= Math.min(height - 1, cy + radius); y += 1) {
      for (let x = Math.max(0, cx - radius); x <= Math.min(width - 1, cx + radius); x += 1) {
        if ((x - cx) * (x - cx) + (y - cy) * (y - cy) > radius * radius) {
          continue;
        }
        const offset = (y * width + x) * 4;
        const value = 228 + Math.floor(hashNoise(x, y, seed + index) * 27);
        output[offset] = value;
        output[offset + 1] = value;
        output[offset + 2] = value;
      }
    }
  }

  const scratchCount = Math.round(scratches * 8);
  for (let index = 0; index < scratchCount; index += 1) {
    const scratchX = Math.floor(hashNoise(index, seed + 23, seed + 29) * width);
    const scratchWidth = 1 + Math.floor(hashNoise(index, seed + 31, seed + 37) * 2);
    for (let y = 0; y < height; y += 1) {
      const fade = 0.55 + hashNoise(y, index, seed + 41) * 0.45;
      for (let w = 0; w < scratchWidth; w += 1) {
        const x = Math.min(width - 1, scratchX + w);
        const offset = (y * width + x) * 4;
        output[offset] = Math.min(255, output[offset] + fade * 90);
        output[offset + 1] = Math.min(255, output[offset + 1] + fade * 90);
        output[offset + 2] = Math.min(255, output[offset + 2] + fade * 85);
      }
    }
  }
};

const addDrag = (
  output: Uint8ClampedArray,
  width: number,
  height: number,
  drag: number,
  seed: number,
) => {
  if (drag <= 0.001) {
    return;
  }
  for (let x = 0; x < width; x += 1) {
    const columnBias = (hashNoise(x, seed + 51, seed + 59) - 0.5) * drag * 80;
    let carry = 0;
    for (let y = 0; y < height; y += 1) {
      const offset = (y * width + x) * 4;
      const brightness =
        (output[offset] + output[offset + 1] + output[offset + 2]) / 3 / 255;
      carry = carry * 0.94 + Math.max(0, brightness - 0.7) * drag * 30;
      const shift = columnBias + carry;
      output[offset] = Math.min(255, Math.max(0, output[offset] + shift));
      output[offset + 1] = Math.min(255, Math.max(0, output[offset + 1] + shift * 0.72));
      output[offset + 2] = Math.min(255, Math.max(0, output[offset + 2] + shift * 0.45));
    }
  }
};

const renderExposureStack = (
  exposureInputs: { id: string; weight: number; offsetX: number; offsetY: number; rotation: number }[],
  recipe: RenderRecipe,
  maxDimension: number,
) => {
  const firstExposure = exposures.get(exposureInputs[0].id);
  if (!firstExposure) {
    throw new Error("No exposure data is loaded.");
  }

  const longestSide = Math.max(firstExposure.width, firstExposure.height);
  const scale = Math.min(1, maxDimension / longestSide);
  const width = Math.max(1, Math.round(firstExposure.width * scale));
  const height = Math.max(1, Math.round(firstExposure.height * scale));
  const pixelCount = width * height;

  const linear = new Float32Array(pixelCount * 3);
  const luminance = new Float32Array(pixelCount);
  const exposureGain =
    0.92 *
    2 ** (recipe.exposureComp + recipe.pushPullStops * 0.35) *
    Math.sqrt(recipe.filmIso / Math.max(1, recipe.iso));
  const shutterBias = Math.max(0.6, Math.min(1.5, Math.sqrt(recipe.shutterSeconds * 125)));
  const apertureBias = Math.max(0.7, Math.min(1.25, 4 / Math.max(1.4, recipe.aperture)));
  const stackBias = exposureGain * shutterBias * apertureBias;

  for (let index = 0; index < exposureInputs.length; index += 1) {
    const exposureInput = exposureInputs[index];
    const exposure = exposures.get(exposureInput.id);
    if (!exposure) {
      continue;
    }
    const imageData =
      Math.abs(exposureInput.offsetX) > 0.0001 ||
      Math.abs(exposureInput.offsetY) > 0.0001 ||
      Math.abs(exposureInput.rotation) > 0.0001
        ? drawTransformed(
            exposure.bitmap,
            width,
            height,
            exposureInput.offsetX,
            exposureInput.offsetY,
            exposureInput.rotation,
          )
        : drawScaled(exposure.bitmap, width, height);
    const weight = exposureInput.weight * (0.9 + index * 0.12);
    for (let pixel = 0; pixel < pixelCount; pixel += 1) {
      const offset = pixel * 4;
      linear[pixel * 3] += srgbToLinear(imageData.data[offset]) * weight * stackBias;
      linear[pixel * 3 + 1] += srgbToLinear(imageData.data[offset + 1]) * weight * stackBias;
      linear[pixel * 3 + 2] += srgbToLinear(imageData.data[offset + 2]) * weight * stackBias;
    }
  }

  for (let pixel = 0; pixel < pixelCount; pixel += 1) {
    const r = linear[pixel * 3];
    const g = linear[pixel * 3 + 1];
    const b = linear[pixel * 3 + 2];
    luminance[pixel] = r * 0.2126 + g * 0.7152 + b * 0.0722;
  }

  const halationMask = new Float32Array(pixelCount);
  for (let pixel = 0; pixel < pixelCount; pixel += 1) {
    const value = Math.max(0, luminance[pixel] - 0.55);
    halationMask[pixel] = value * value;
  }

  const halationStrength = recipe.filmHalation * 0.5 + recipe.halation * 0.7 + recipe.lensBloom * 0.25;
  const halation = gaussianBlur(
    halationMask,
    width,
    height,
    2 + halationStrength * 8,
  );

  const output = new Uint8ClampedArray(pixelCount * 4);
  const fog = 0.01 + recipe.fog * 0.06 + Math.max(0, recipe.temperatureC - 20) * 0.002;
  const contrast = 0.82 + recipe.filmContrast * 0.55 + recipe.contrast * 0.75 + recipe.pushPullStops * 0.08;
  const saturation = recipe.filmKind === "bw-negative"
    ? 0
    : recipe.filmSaturation * 0.6 + recipe.saturation * 0.9;
  const warmth = recipe.filmWarmth + (recipe.temperatureC - 20) * 0.015;
  const vignetteStrength = recipe.lensVignette + (1 - recipe.cameraFormatWeight) * 0.08;
  const grainStrength = recipe.filmGrain * 0.45 + recipe.grain * 0.7;

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const pixel = y * width + x;
      const centerX = (x / Math.max(1, width - 1)) * 2 - 1;
      const centerY = (y / Math.max(1, height - 1)) * 2 - 1;
      const radial = Math.min(1, Math.sqrt(centerX * centerX + centerY * centerY));
      const vignette = 1 - vignetteStrength * radial * radial;

      let r = 1 - Math.exp(-(linear[pixel * 3] * vignette + fog));
      let g = 1 - Math.exp(-(linear[pixel * 3 + 1] * vignette + fog));
      let b = 1 - Math.exp(-(linear[pixel * 3 + 2] * vignette + fog));

      if (recipe.filmKind === "bw-negative") {
        const mono = r * 0.26 + g * 0.62 + b * 0.12;
        r = mono * (1 + warmth * 0.18);
        g = mono;
        b = mono * (1 - warmth * 0.12);
      }

      const shoulder = 0.92;
      r = Math.pow(clamp01(lerp(r, r / (r + shoulder), 0.58)), contrast);
      g = Math.pow(clamp01(lerp(g, g / (g + shoulder), 0.58)), contrast);
      b = Math.pow(clamp01(lerp(b, b / (b + shoulder), 0.58)), contrast);

      const glow = halation[pixel] * halationStrength;
      r = clamp01(r + glow * 0.85);
      g = clamp01(g + glow * 0.28);
      b = clamp01(b + glow * 0.12);

      const luma = r * 0.2126 + g * 0.7152 + b * 0.0722;
      r = luma + (r - luma) * saturation;
      g = luma + (g - luma) * saturation;
      b = luma + (b - luma) * saturation;

      r = clamp01(r * (1 + warmth * 0.14));
      g = clamp01(g);
      b = clamp01(b * (1 - warmth * 0.12));

      const grain =
        (hashNoise(x, y, recipe.seed) - 0.5) * grainStrength * 0.09 +
        (hashNoise(x * 0.25, y * 0.25, recipe.seed + 19) - 0.5) * grainStrength * 0.14;
      r = clamp01(r + grain);
      g = clamp01(g + grain * 0.94);
      b = clamp01(b + grain * 0.88);

      const offset = pixel * 4;
      output[offset] = Math.round(linearToSrgb(r));
      output[offset + 1] = Math.round(linearToSrgb(g));
      output[offset + 2] = Math.round(linearToSrgb(b));
      output[offset + 3] = 255;
    }
  }

  addLightLeak(output, width, height, recipe.lightLeak, recipe.seed);
  addDustAndScratches(output, width, height, recipe.dust, recipe.scratches, recipe.seed);
  addDrag(output, width, height, recipe.drag, recipe.seed);

  return { output, width, height };
};

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const message = event.data;

  try {
    if (message.type === "load-exposure") {
      const blob = new Blob([message.buffer]);
      const bitmap = await createImageBitmap(blob, {
        resizeQuality: "high",
      });
      const longestSide = Math.max(bitmap.width, bitmap.height);
      const scale = Math.min(1, message.maxDimension / longestSide);
      const width = Math.max(1, Math.round(bitmap.width * scale));
      const height = Math.max(1, Math.round(bitmap.height * scale));

      let storedBitmap = bitmap;
      if (scale < 1) {
        const canvas = makeCanvas(width, height);
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          throw new Error("2D canvas context is unavailable.");
        }
        ctx.drawImage(bitmap, 0, 0, width, height);
        storedBitmap = canvas.transferToImageBitmap();
        bitmap.close();
      }

      const previous = exposures.get(message.exposureId);
      previous?.bitmap.close();
      exposures.set(message.exposureId, {
        bitmap: storedBitmap,
        width,
        height,
      });

      post({
        type: "exposure-loaded",
        exposureId: message.exposureId,
        width,
        height,
      });
      return;
    }

    if (message.type === "remove-exposure") {
      const exposure = exposures.get(message.exposureId);
      exposure?.bitmap.close();
      exposures.delete(message.exposureId);
      return;
    }

    const startedAt = performance.now();
    const { output, width, height } = renderExposureStack(
      message.exposures,
      message.recipe,
      message.maxDimension,
    );
    const canvas = makeCanvas(width, height);
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      throw new Error("2D canvas context is unavailable.");
    }
    ctx.putImageData(new ImageData(output, width, height), 0, 0);
    const blob = await canvas.convertToBlob({
      type: message.format,
      quality: message.format === "image/jpeg" ? 0.95 : undefined,
    });

    post({
      type: "rendered",
      jobId: message.jobId,
      kind: message.kind,
      blob,
      width,
      height,
      renderMs: Math.round(performance.now() - startedAt),
    });
  } catch (error) {
    post({
      type: "error",
      jobId: "jobId" in message ? message.jobId : undefined,
      exposureId: "exposureId" in message ? message.exposureId : undefined,
      message: error instanceof Error ? error.message : "Unknown worker error.",
    });
  }
};
