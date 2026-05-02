import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useDeferredValue,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";
import { cameraPresetMap, filmPresetMap, lensPresetMap } from "../lib/presets";
import type { RenderRecipe, WorkerRequest, WorkerResponse } from "../lib/pipeline";

type ExposureItem = {
  id: string;
  name: string;
  sourceUrl: string;
  enabled: boolean;
  weight: number;
  offsetX: number;
  offsetY: number;
  rotation: number;
  loaded: boolean;
  width: number;
  height: number;
};

type DevelopmentSettings = {
  temperatureC: number;
  agitation: number;
  pushPullStops: number;
  grain: number;
  halation: number;
  contrast: number;
  saturation: number;
  fog: number;
  lightLeak: number;
  dust: number;
  scratches: number;
  drag: number;
  seed: number;
};

type SnapshotItem = {
  id: string;
  name: string;
  filmId: string;
  cameraId: string;
  lensId: string;
  settings: LabProject["settings"];
  development: DevelopmentSettings;
};

type LabProject = {
  title: string;
  filmId: string;
  cameraId: string;
  lensId: string;
  settings: {
    iso: number;
    aperture: number;
    shutterSeconds: number;
    exposureComp: number;
  };
  development: DevelopmentSettings;
  exposures: ExposureItem[];
  snapshots: SnapshotItem[];
  compareSnapshotId: string | null;
};

type PreviewState = {
  url: string;
  width: number;
  height: number;
  renderMs: number;
};

type RenderStatus = "idle" | "loading" | "ready" | "error";

type FilmLabContextValue = {
  project: LabProject;
  preview: PreviewState | null;
  comparePreview: PreviewState | null;
  renderStatus: RenderStatus;
  renderError: string | null;
  setTitle: (title: string) => void;
  setFilm: (filmId: string) => void;
  setCamera: (cameraId: string) => void;
  setLens: (lensId: string) => void;
  updateSettings: (patch: Partial<LabProject["settings"]>) => void;
  updateDevelopment: (patch: Partial<DevelopmentSettings>) => void;
  importExposures: (files: FileList | File[]) => Promise<void>;
  updateExposure: (exposureId: string, patch: Partial<ExposureItem>) => void;
  removeExposure: (exposureId: string) => void;
  moveExposure: (exposureId: string, direction: -1 | 1) => void;
  exportFinal: (format: "image/png" | "image/jpeg") => Promise<Blob>;
  resetProject: () => void;
  saveSnapshot: (name?: string) => void;
  loadSnapshot: (snapshotId: string) => void;
  removeSnapshot: (snapshotId: string) => void;
  setCompareSnapshot: (snapshotId: string | null) => void;
  randomizeAccidents: () => void;
};

type Action =
  | { type: "set-title"; title: string }
  | { type: "set-film"; filmId: string }
  | { type: "set-camera"; cameraId: string }
  | { type: "set-lens"; lensId: string }
  | { type: "update-settings"; patch: Partial<LabProject["settings"]> }
  | { type: "update-development"; patch: Partial<DevelopmentSettings> }
  | { type: "add-exposure"; exposure: ExposureItem }
  | { type: "update-exposure"; exposureId: string; patch: Partial<ExposureItem> }
  | { type: "remove-exposure"; exposureId: string }
  | { type: "move-exposure"; exposureId: string; direction: -1 | 1 }
  | { type: "save-snapshot"; snapshot: SnapshotItem }
  | { type: "load-snapshot"; snapshotId: string }
  | { type: "remove-snapshot"; snapshotId: string }
  | { type: "set-compare-snapshot"; snapshotId: string | null }
  | { type: "reset"; project: LabProject };

const STORAGE_KEY = "film-lab-project-v1";

export const createDefaultProject = (): LabProject => ({
  title: "",
  filmId: "vision-250d",
  cameraId: "mamiya-7",
  lensId: "mamiya-80",
  settings: {
    iso: 250,
    aperture: 5.6,
    shutterSeconds: 1 / 125,
    exposureComp: 0,
  },
  development: {
    temperatureC: 20,
    agitation: 0.45,
    pushPullStops: 0,
    grain: 0.36,
    halation: 0.4,
    contrast: 0.5,
    saturation: 0.48,
    fog: 0.08,
    lightLeak: 0,
    dust: 0,
    scratches: 0,
    drag: 0,
    seed: 17,
  },
  exposures: [],
  snapshots: [],
  compareSnapshotId: null,
});

const isValidFilmId = (value: unknown): value is string =>
  typeof value === "string" && filmPresetMap.has(value);

const isValidCameraId = (value: unknown): value is string =>
  typeof value === "string" && cameraPresetMap.has(value);

const isValidLensId = (value: unknown): value is string =>
  typeof value === "string" && lensPresetMap.has(value);

const sanitizeProject = (input: unknown): LabProject => {
  const fallback = createDefaultProject();
  if (!input || typeof input !== "object") {
    return fallback;
  }
  const project = input as Partial<LabProject>;
  const snapshots = Array.isArray(project.snapshots)
    ? project.snapshots.filter(
        (snapshot): snapshot is SnapshotItem =>
          Boolean(
            snapshot &&
              typeof snapshot.id === "string" &&
              typeof snapshot.name === "string" &&
              isValidFilmId(snapshot.filmId) &&
              isValidCameraId(snapshot.cameraId) &&
              isValidLensId(snapshot.lensId),
          ),
      )
    : [];
  const compareSnapshotId =
    typeof project.compareSnapshotId === "string" &&
    snapshots.some((snapshot) => snapshot.id === project.compareSnapshotId)
      ? project.compareSnapshotId
      : null;

  return {
    ...fallback,
    ...project,
    filmId: isValidFilmId(project.filmId) ? project.filmId : fallback.filmId,
    cameraId: isValidCameraId(project.cameraId) ? project.cameraId : fallback.cameraId,
    lensId: isValidLensId(project.lensId) ? project.lensId : fallback.lensId,
    settings: {
      ...fallback.settings,
      ...project.settings,
    },
    development: {
      ...fallback.development,
      ...project.development,
    },
    exposures: [],
    snapshots,
    compareSnapshotId,
  };
};

const reducer = (state: LabProject, action: Action): LabProject => {
  switch (action.type) {
    case "set-title":
      return { ...state, title: action.title };
    case "set-film": {
      const film = filmPresetMap.get(action.filmId);
      if (!film) {
        return state;
      }
      return {
        ...state,
        filmId: action.filmId,
        settings: {
          ...state.settings,
          iso: film.iso,
        },
      };
    }
    case "set-camera":
      return cameraPresetMap.has(action.cameraId)
        ? { ...state, cameraId: action.cameraId }
        : state;
    case "set-lens":
      return lensPresetMap.has(action.lensId)
        ? { ...state, lensId: action.lensId }
        : state;
    case "update-settings":
      return { ...state, settings: { ...state.settings, ...action.patch } };
    case "update-development":
      return {
        ...state,
        development: { ...state.development, ...action.patch },
      };
    case "add-exposure":
      return { ...state, exposures: [...state.exposures, action.exposure] };
    case "update-exposure":
      return {
        ...state,
        exposures: state.exposures.map((exposure) =>
          exposure.id === action.exposureId ? { ...exposure, ...action.patch } : exposure,
        ),
      };
    case "remove-exposure":
      return {
        ...state,
        exposures: state.exposures.filter((exposure) => exposure.id !== action.exposureId),
      };
    case "move-exposure": {
      const index = state.exposures.findIndex((exposure) => exposure.id === action.exposureId);
      if (index < 0) {
        return state;
      }
      const nextIndex = index + action.direction;
      if (nextIndex < 0 || nextIndex >= state.exposures.length) {
        return state;
      }
      const exposures = [...state.exposures];
      const [moved] = exposures.splice(index, 1);
      exposures.splice(nextIndex, 0, moved);
      return { ...state, exposures };
    }
    case "save-snapshot":
      return {
        ...state,
        snapshots: [action.snapshot, ...state.snapshots],
        compareSnapshotId: action.snapshot.id,
      };
    case "load-snapshot": {
      const snapshot = state.snapshots.find((item) => item.id === action.snapshotId);
      if (!snapshot) {
        return state;
      }
      return {
        ...state,
        filmId: snapshot.filmId,
        cameraId: snapshot.cameraId,
        lensId: snapshot.lensId,
        settings: { ...snapshot.settings },
        development: { ...snapshot.development },
      };
    }
    case "remove-snapshot":
      return {
        ...state,
        snapshots: state.snapshots.filter((snapshot) => snapshot.id !== action.snapshotId),
        compareSnapshotId:
          state.compareSnapshotId === action.snapshotId ? null : state.compareSnapshotId,
      };
    case "set-compare-snapshot":
      return { ...state, compareSnapshotId: action.snapshotId };
    case "reset":
      return action.project;
    default:
      return state;
  }
};

const FilmLabContext = createContext<FilmLabContextValue | null>(null);

type RecipeSource = Pick<LabProject, "filmId" | "cameraId" | "lensId" | "settings" | "development">;

const buildRecipe = (source: RecipeSource): RenderRecipe => {
  const film = filmPresetMap.get(source.filmId)!;
  const camera = cameraPresetMap.get(source.cameraId)!;
  const lens = lensPresetMap.get(source.lensId)!;
  return {
    filmId: film.id,
    filmKind: film.kind,
    filmContrast: film.contrast,
    filmSaturation: film.saturation,
    filmGrain: film.grain,
    filmHalation: film.halation,
    filmWarmth: film.warmth,
    filmIso: film.iso,
    cameraFormatWeight: camera.formatWeight,
    lensBloom: lens.bloom + lens.halationBias * 0.35,
    lensVignette: lens.vignette + camera.edgeFalloff,
    iso: source.settings.iso,
    aperture: source.settings.aperture,
    shutterSeconds: source.settings.shutterSeconds,
    exposureComp: source.settings.exposureComp,
    grain: source.development.grain,
    halation: source.development.halation + lens.halationBias,
    contrast: source.development.contrast,
    saturation: source.development.saturation,
    temperatureC: source.development.temperatureC,
    agitation: source.development.agitation,
    pushPullStops: source.development.pushPullStops,
    fog: source.development.fog,
    lightLeak: source.development.lightLeak,
    dust: source.development.dust,
    scratches: source.development.scratches,
    drag: source.development.drag,
    seed: source.development.seed + Math.round(lens.halationBias * 100),
  };
};

const toRenderExposures = (project: LabProject) =>
  project.exposures
    .filter((exposure) => exposure.enabled && exposure.loaded)
    .map((exposure) => ({
      id: exposure.id,
      weight: exposure.weight,
      offsetX: exposure.offsetX,
      offsetY: exposure.offsetY,
      rotation: exposure.rotation,
    }));

export function FilmLabProvider({ children }: PropsWithChildren) {
  const [project, dispatch] = useReducer(reducer, undefined, () => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) {
      return createDefaultProject();
    }
    try {
      return sanitizeProject(JSON.parse(stored));
    } catch {
      return createDefaultProject();
    }
  });
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [comparePreview, setComparePreview] = useState<PreviewState | null>(null);
  const [renderStatus, setRenderStatus] = useState<RenderStatus>("idle");
  const [renderError, setRenderError] = useState<string | null>(null);

  const workerRef = useRef<Worker | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const compareUrlRef = useRef<string | null>(null);
  const latestPreviewJobIdRef = useRef<string | null>(null);
  const latestCompareJobIdRef = useRef<string | null>(null);
  const pendingJobsRef = useRef(
    new Map<string, { resolve: (blob: Blob) => void; reject: (reason?: unknown) => void }>(),
  );

  useEffect(() => {
    const snapshot = {
      ...project,
      exposures: [],
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
  }, [project]);

  useEffect(() => {
    const worker = new Worker(new URL("../workers/pipeline.worker.ts", import.meta.url), {
      type: "module",
    });
    workerRef.current = worker;

    worker.onmessage = (event: MessageEvent<WorkerResponse>) => {
      const message = event.data;
      if (message.type === "exposure-loaded") {
        dispatch({
          type: "update-exposure",
          exposureId: message.exposureId,
          patch: { loaded: true, width: message.width, height: message.height },
        });
        return;
      }

      if (message.type === "rendered") {
        if (message.kind === "preview") {
          if (latestPreviewJobIdRef.current !== message.jobId) {
            return;
          }
          const nextUrl = URL.createObjectURL(message.blob);
          if (previewUrlRef.current) {
            URL.revokeObjectURL(previewUrlRef.current);
          }
          previewUrlRef.current = nextUrl;
          startTransition(() => {
            setPreview({
              url: nextUrl,
              width: message.width,
              height: message.height,
              renderMs: message.renderMs,
            });
            setRenderStatus("ready");
            setRenderError(null);
          });
          return;
        }

        if (message.kind === "compare") {
          if (latestCompareJobIdRef.current !== message.jobId) {
            return;
          }
          const nextUrl = URL.createObjectURL(message.blob);
          if (compareUrlRef.current) {
            URL.revokeObjectURL(compareUrlRef.current);
          }
          compareUrlRef.current = nextUrl;
          startTransition(() => {
            setComparePreview({
              url: nextUrl,
              width: message.width,
              height: message.height,
              renderMs: message.renderMs,
            });
          });
          return;
        }

        const pending = pendingJobsRef.current.get(message.jobId);
        if (pending) {
          pendingJobsRef.current.delete(message.jobId);
          setRenderStatus("ready");
          setRenderError(null);
          pending.resolve(message.blob);
        }
        return;
      }

      setRenderStatus("error");
      setRenderError(message.message);
      if (message.jobId) {
        const pending = pendingJobsRef.current.get(message.jobId);
        if (pending) {
          pendingJobsRef.current.delete(message.jobId);
          pending.reject(new Error(message.message));
        }
      }
    };

    return () => {
      worker.terminate();
      workerRef.current = null;
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
      }
      if (compareUrlRef.current) {
        URL.revokeObjectURL(compareUrlRef.current);
      }
    };
  }, []);

  const deferredProject = useDeferredValue(project);

  useEffect(() => {
    const exposures = toRenderExposures(deferredProject);
    if (!workerRef.current) {
      return;
    }
    if (exposures.length === 0) {
      setPreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        previewUrlRef.current = null;
        return null;
      });
      setComparePreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        compareUrlRef.current = null;
        return null;
      });
      setRenderStatus("idle");
      setRenderError(null);
      return;
    }

    setRenderStatus("loading");
    const timeout = window.setTimeout(() => {
      const jobId = crypto.randomUUID();
      latestPreviewJobIdRef.current = jobId;
      workerRef.current?.postMessage({
        type: "render",
        kind: "preview",
        jobId,
        exposures,
        recipe: buildRecipe(deferredProject),
        maxDimension: 1480,
        format: "image/png",
      } satisfies WorkerRequest);
    }, 120);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [deferredProject]);

  useEffect(() => {
    const exposures = toRenderExposures(project);
    const snapshot = project.snapshots.find((item) => item.id === project.compareSnapshotId);
    if (!workerRef.current || !snapshot || exposures.length === 0) {
      setComparePreview((current) => {
        if (current?.url) {
          URL.revokeObjectURL(current.url);
        }
        compareUrlRef.current = null;
        return null;
      });
      return;
    }

    const timeout = window.setTimeout(() => {
      const jobId = crypto.randomUUID();
      latestCompareJobIdRef.current = jobId;
      workerRef.current?.postMessage({
        type: "render",
        kind: "compare",
        jobId,
        exposures,
        recipe: buildRecipe(snapshot),
        maxDimension: 1480,
        format: "image/png",
      } satisfies WorkerRequest);
    }, 80);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [project.compareSnapshotId, project.exposures, project.snapshots]);

  const setTitle = useCallback((title: string) => {
    dispatch({ type: "set-title", title });
  }, []);

  const setFilm = useCallback((filmId: string) => {
    dispatch({ type: "set-film", filmId });
  }, []);

  const setCamera = useCallback((cameraId: string) => {
    dispatch({ type: "set-camera", cameraId });
  }, []);

  const setLens = useCallback((lensId: string) => {
    dispatch({ type: "set-lens", lensId });
  }, []);

  const updateSettings = useCallback((patch: Partial<LabProject["settings"]>) => {
    dispatch({ type: "update-settings", patch });
  }, []);

  const updateDevelopment = useCallback((patch: Partial<DevelopmentSettings>) => {
    dispatch({ type: "update-development", patch });
  }, []);

  const importExposures = useCallback(
    async (files: FileList | File[]) => {
      const worker = workerRef.current;
      if (!worker) {
        return;
      }
      const fileList = Array.from(files);
      if (project.exposures.length === 0 && fileList.length > 0) {
        dispatch({ type: "set-title", title: fileList[0].name });
      }
      for (const file of fileList) {
        const exposureId = crypto.randomUUID();
        const sourceUrl = URL.createObjectURL(file);
        dispatch({
          type: "add-exposure",
          exposure: {
            id: exposureId,
            name: file.name,
            sourceUrl,
            enabled: true,
            weight: 1,
            offsetX: 0,
            offsetY: 0,
            rotation: 0,
            loaded: false,
            width: 0,
            height: 0,
          },
        });
        const buffer = await file.arrayBuffer();
        worker.postMessage(
          {
            type: "load-exposure",
            exposureId,
            fileName: file.name,
            buffer,
            maxDimension: 2400,
          } satisfies WorkerRequest,
          [buffer],
        );
      }
    },
    [project.exposures.length],
  );

  const updateExposure = useCallback((exposureId: string, patch: Partial<ExposureItem>) => {
    dispatch({ type: "update-exposure", exposureId, patch });
  }, []);

  const removeExposure = useCallback(
    (exposureId: string) => {
      const exposure = project.exposures.find((item) => item.id === exposureId);
      if (exposure?.sourceUrl) {
        URL.revokeObjectURL(exposure.sourceUrl);
      }
      dispatch({ type: "remove-exposure", exposureId });
      workerRef.current?.postMessage({
        type: "remove-exposure",
        exposureId,
      } satisfies WorkerRequest);
    },
    [project.exposures],
  );

  const moveExposure = useCallback((exposureId: string, direction: -1 | 1) => {
    dispatch({ type: "move-exposure", exposureId, direction });
  }, []);

  const exportFinal = useCallback(
    (format: "image/png" | "image/jpeg") => {
      const worker = workerRef.current;
      if (!worker) {
        return Promise.reject(new Error("Render worker is not ready."));
      }
      const exposures = toRenderExposures(project);
      if (exposures.length === 0) {
        return Promise.reject(new Error("Expose at least one image first."));
      }
      const jobId = crypto.randomUUID();
      setRenderStatus("loading");
      return new Promise<Blob>((resolve, reject) => {
        pendingJobsRef.current.set(jobId, { resolve, reject });
        worker.postMessage({
          type: "render",
          kind: "export",
          jobId,
          exposures,
          recipe: buildRecipe(project),
          maxDimension: 3200,
          format,
        } satisfies WorkerRequest);
      });
    },
    [project],
  );

  const resetProject = useCallback(() => {
    for (const exposure of project.exposures) {
      if (exposure.sourceUrl) {
        URL.revokeObjectURL(exposure.sourceUrl);
      }
      workerRef.current?.postMessage({
        type: "remove-exposure",
        exposureId: exposure.id,
      } satisfies WorkerRequest);
    }
    dispatch({ type: "reset", project: createDefaultProject() });
    setPreview(null);
    setComparePreview(null);
    setRenderError(null);
    setRenderStatus("idle");
  }, [project.exposures]);

  const saveSnapshot = useCallback(
    (name?: string) => {
      const snapshotNumber = project.snapshots.length + 1;
      dispatch({
        type: "save-snapshot",
        snapshot: {
          id: crypto.randomUUID(),
          name: name?.trim() || `Snapshot ${snapshotNumber}`,
          filmId: project.filmId,
          cameraId: project.cameraId,
          lensId: project.lensId,
          settings: { ...project.settings },
          development: { ...project.development },
        },
      });
    },
    [project],
  );

  const loadSnapshot = useCallback((snapshotId: string) => {
    dispatch({ type: "load-snapshot", snapshotId });
  }, []);

  const removeSnapshot = useCallback((snapshotId: string) => {
    dispatch({ type: "remove-snapshot", snapshotId });
  }, []);

  const setCompareSnapshot = useCallback((snapshotId: string | null) => {
    dispatch({ type: "set-compare-snapshot", snapshotId });
  }, []);

  const randomizeAccidents = useCallback(() => {
    const nextSeed = project.development.seed + 17;
    const rand = (offset: number) =>
      (Math.sin(nextSeed * 12.9898 + offset * 78.233) * 43758.5453) % 1;
    const positive = (value: number) => Math.abs(value);
    dispatch({
      type: "update-development",
      patch: {
        lightLeak: Number((positive(rand(1)) * 0.35).toFixed(2)),
        dust: Number((positive(rand(2)) * 0.28).toFixed(2)),
        scratches: Number((positive(rand(3)) * 0.22).toFixed(2)),
        drag: Number((positive(rand(4)) * 0.3).toFixed(2)),
        seed: nextSeed,
      },
    });
  }, [project.development.seed]);

  const value = useMemo<FilmLabContextValue>(
    () => ({
      project,
      preview,
      comparePreview,
      renderStatus,
      renderError,
      setTitle,
      setFilm,
      setCamera,
      setLens,
      updateSettings,
      updateDevelopment,
      importExposures,
      updateExposure,
      removeExposure,
      moveExposure,
      exportFinal,
      resetProject,
      saveSnapshot,
      loadSnapshot,
      removeSnapshot,
      setCompareSnapshot,
      randomizeAccidents,
    }),
    [
      comparePreview,
      exportFinal,
      importExposures,
      loadSnapshot,
      moveExposure,
      preview,
      project,
      randomizeAccidents,
      removeExposure,
      removeSnapshot,
      renderError,
      renderStatus,
      resetProject,
      saveSnapshot,
      setCamera,
      setCompareSnapshot,
      setFilm,
      setLens,
      setTitle,
      updateDevelopment,
      updateExposure,
      updateSettings,
    ],
  );

  return <FilmLabContext.Provider value={value}>{children}</FilmLabContext.Provider>;
}

export const useFilmLab = () => {
  const context = useContext(FilmLabContext);
  if (!context) {
    throw new Error("useFilmLab must be used inside FilmLabProvider");
  }
  return context;
};
