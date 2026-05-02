export type WorkerLoadExposureMessage = {
  type: "load-exposure";
  exposureId: string;
  fileName: string;
  buffer: ArrayBuffer;
  maxDimension: number;
};

export type WorkerRemoveExposureMessage = {
  type: "remove-exposure";
  exposureId: string;
};

export type RenderRecipe = {
  filmId: string;
  filmKind: "color-negative" | "bw-negative" | "slide";
  filmContrast: number;
  filmSaturation: number;
  filmGrain: number;
  filmHalation: number;
  filmWarmth: number;
  filmIso: number;
  cameraFormatWeight: number;
  lensBloom: number;
  lensVignette: number;
  iso: number;
  aperture: number;
  shutterSeconds: number;
  exposureComp: number;
  grain: number;
  halation: number;
  contrast: number;
  saturation: number;
  temperatureC: number;
  agitation: number;
  pushPullStops: number;
  fog: number;
  lightLeak: number;
  dust: number;
  scratches: number;
  drag: number;
  seed: number;
};

export type RenderExposure = {
  id: string;
  weight: number;
  offsetX: number;
  offsetY: number;
  rotation: number;
};

export type WorkerRenderMessage = {
  type: "render";
  jobId: string;
  exposures: RenderExposure[];
  recipe: RenderRecipe;
  maxDimension: number;
  kind: "preview" | "compare" | "export";
  format: "image/png" | "image/jpeg";
};

export type WorkerRequest =
  | WorkerLoadExposureMessage
  | WorkerRemoveExposureMessage
  | WorkerRenderMessage;

export type WorkerExposureLoadedMessage = {
  type: "exposure-loaded";
  exposureId: string;
  width: number;
  height: number;
};

export type WorkerRenderedMessage = {
  type: "rendered";
  jobId: string;
  kind: "preview" | "compare" | "export";
  blob: Blob;
  width: number;
  height: number;
  renderMs: number;
};

export type WorkerErrorMessage = {
  type: "error";
  jobId?: string;
  exposureId?: string;
  message: string;
};

export type WorkerResponse =
  | WorkerExposureLoadedMessage
  | WorkerRenderedMessage
  | WorkerErrorMessage;
