import { useRef, useState, type ReactNode } from "react";
import {
  Aperture,
  Camera,
  ChevronDown,
  ChevronUp,
  CircleDot,
  Download,
  Droplets,
  Film,
  ImagePlus,
  Images,
  Layers3,
  LoaderCircle,
  RefreshCcw,
  RotateCcw,
  Save,
  SlidersHorizontal,
  Sparkles,
  SplitSquareHorizontal,
  SunMedium,
  Thermometer,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import {
  cameraPresetMap,
  cameraPresets,
  filmPresetMap,
  filmPresets,
  lensPresetMap,
  lensPresets,
} from "../lib/presets";
import { createDefaultProject, useFilmLab } from "../store/filmLab";

const APERTURES = [1.4, 2, 2.8, 4, 5.6, 8, 11, 16];
const SHUTTERS = [1 / 1000, 1 / 500, 1 / 250, 1 / 125, 1 / 60, 1 / 30, 1 / 15, 1 / 8, 1 / 4, 1 / 2, 1];

const downloadBlob = (blob: Blob, filename: string) => {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
};

const formatShutter = (seconds: number) =>
  seconds >= 1 ? `${seconds.toFixed(1)}s` : `1/${Math.round(1 / seconds)}`;

const replaceExtension = (filename: string, nextExtension: string) => {
  const trimmed = filename.trim();
  if (!trimmed) {
    return `film-lab.${nextExtension}`;
  }
  const dotIndex = trimmed.lastIndexOf(".");
  if (dotIndex <= 0) {
    return `${trimmed}.${nextExtension}`;
  }
  return `${trimmed.slice(0, dotIndex)}.${nextExtension}`;
};

function DetailGrid({ items }: { items: Array<{ label: string; value: string }> }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[color:var(--color-text-soft)]">
      {items.map((item) => (
        <div key={item.label} className="contents">
          <span>{item.label}</span>
          <span className="text-right text-[color:var(--color-text)]">{item.value}</span>
        </div>
      ))}
    </div>
  );
}

type RibbonMenuProps = {
  icon: LucideIcon;
  label: string;
  children: ReactNode;
};

function RibbonMenu({ icon: Icon, label, children }: RibbonMenuProps) {
  return (
    <details className="group relative">
      <summary className="icon-button flex list-none items-center gap-2 px-3 py-2 text-sm [&::-webkit-details-marker]:hidden">
        <Icon className="h-4 w-4" />
        <span>{label}</span>
        <ChevronDown className="h-4 w-4 text-[color:var(--color-text-soft)] group-open:rotate-180" />
      </summary>
      <div className="absolute left-0 top-[calc(100%+6px)] z-20 w-[320px] border border-[color:var(--color-border)] bg-[color:var(--color-panel)] p-3 shadow-[0_16px_40px_rgba(0,0,0,0.35)]">
        {children}
      </div>
    </details>
  );
}

type QuickSliderProps = {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  defaultValue: number;
  onChange: (value: number) => void;
};

function QuickSlider({
  label,
  value,
  min,
  max,
  step,
  display,
  defaultValue,
  onChange,
}: QuickSliderProps) {
  return (
    <label className="grid gap-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[color:var(--color-text-soft)]">{label}</span>
        <div className="flex items-center gap-2">
          <span>{display}</span>
          <button
            className="text-[10px] text-[color:var(--color-text-soft)] hover:text-[color:var(--color-text)]"
            onClick={() => onChange(defaultValue)}
            type="button"
          >
            Default
          </button>
        </div>
      </div>
      <input
        className="slider w-full"
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

type SelectFieldProps = {
  icon: LucideIcon;
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
};

function SelectField({ icon: Icon, label, value, onChange, children }: SelectFieldProps) {
  return (
    <label className="grid gap-1">
      <span className="flex items-center gap-2 text-xs uppercase tracking-[0.12em] text-[color:var(--color-text-soft)]">
        <Icon className="h-4 w-4" />
        <span>{label}</span>
      </span>
      <select
        className="control px-3 py-2"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </label>
  );
}

export default function StudioPage() {
  const {
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
  } = useFilmLab();
  const [busyFormat, setBusyFormat] = useState<"image/png" | "image/jpeg" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);
  const [previewMode, setPreviewMode] = useState<"edited" | "compare">("edited");
  const compareTimerRef = useRef<number | null>(null);

  const defaultProject = createDefaultProject();
  const film = filmPresetMap.get(project.filmId) ?? filmPresets[0];
  const camera = cameraPresetMap.get(project.cameraId) ?? cameraPresets[0];
  const lens = lensPresetMap.get(project.lensId) ?? lensPresets[0];
  const loadedFrames = project.exposures.filter((exposure) => exposure.loaded).length;
  const selectedExposure = project.exposures[0] ?? null;
  const compareExposure =
    project.exposures.find((exposure) => exposure.enabled && exposure.loaded) ??
    project.exposures.find((exposure) => exposure.loaded) ??
    null;
  const compareSourceUrl = compareExposure?.sourceUrl ?? null;
  const activePreview = previewMode === "compare" && comparePreview ? comparePreview : preview;
  const previewImageUrl =
    showOriginal && compareSourceUrl ? compareSourceUrl : activePreview?.url ?? null;
  const previewLabel =
    showOriginal && compareSourceUrl
      ? "Original"
      : previewMode === "compare" && comparePreview
        ? "Snapshot B"
        : "Current A";

  const beginCompareHold = () => {
    if (!compareSourceUrl) {
      return;
    }
    if (compareTimerRef.current !== null) {
      window.clearTimeout(compareTimerRef.current);
    }
    compareTimerRef.current = window.setTimeout(() => {
      setShowOriginal(true);
      compareTimerRef.current = null;
    }, 180);
  };

  const endCompareHold = () => {
    if (compareTimerRef.current !== null) {
      window.clearTimeout(compareTimerRef.current);
      compareTimerRef.current = null;
    }
    setShowOriginal(false);
  };

  const handleExport = async (format: "image/png" | "image/jpeg") => {
    setBusyFormat(format);
    setExportError(null);
    try {
      const blob = await exportFinal(format);
      const extension = format === "image/png" ? "png" : "jpg";
      downloadBlob(blob, replaceExtension(project.title, extension));
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "Export failed.");
    } finally {
      setBusyFormat(null);
    }
  };

  return (
    <div className="h-screen bg-[color:var(--color-bg)] text-[color:var(--color-text)]">
      <div className="flex h-full min-w-0 flex-col">
        <header className="border-b border-[color:var(--color-border)] bg-[color:var(--color-panel)]">
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center border border-[color:var(--color-border)] bg-[color:var(--color-panel-strong)]">
                <Film className="h-5 w-5" />
              </div>
              <input
                className="min-w-0 bg-transparent text-lg font-medium outline-none placeholder:text-[color:var(--color-text-soft)]"
                value={project.title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Untitled"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                className="icon-button inline-flex items-center gap-2 px-3 py-2 text-sm"
                onClick={resetProject}
                type="button"
              >
                <RotateCcw className="h-4 w-4" />
                <span>Reset</span>
              </button>
              <button
                className="icon-button inline-flex items-center gap-2 px-3 py-2 text-sm"
                onClick={() => saveSnapshot()}
                type="button"
              >
                <Save className="h-4 w-4" />
                <span>Snapshot</span>
              </button>
              <button
                className="icon-button inline-flex items-center gap-2 px-3 py-2 text-sm disabled:opacity-60"
                disabled={busyFormat !== null}
                onClick={() => void handleExport("image/jpeg")}
                type="button"
              >
                {busyFormat === "image/jpeg" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                <span>JPG</span>
              </button>
              <button
                className="inline-flex items-center gap-2 border border-[color:var(--color-accent)] bg-[color:var(--color-accent)] px-3 py-2 text-sm font-medium text-[color:var(--color-accent-ink)] disabled:opacity-60"
                disabled={busyFormat !== null}
                onClick={() => void handleExport("image/png")}
                type="button"
              >
                {busyFormat === "image/png" ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                <span>PNG</span>
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-start gap-2 border-t border-[color:var(--color-border)] px-4 py-2">
            <label className="icon-button inline-flex cursor-pointer items-center gap-2 px-3 py-2 text-sm">
              <ImagePlus className="h-4 w-4" />
              <span>Add</span>
              <input
                className="sr-only"
                type="file"
                accept="image/png,image/jpeg,image/webp,image/tiff,.tif,.tiff"
                multiple
                onChange={(event) => {
                  if (event.target.files?.length) {
                    void importExposures(event.target.files);
                    event.target.value = "";
                  }
                }}
              />
            </label>
            <button
              className={`icon-button px-3 py-2 text-sm ${previewMode === "edited" ? "border-[color:var(--color-accent)]" : ""}`}
              onClick={() => setPreviewMode("edited")}
              type="button"
            >
              View A
            </button>
            <button
              className={`icon-button px-3 py-2 text-sm ${previewMode === "compare" ? "border-[color:var(--color-accent)]" : ""}`}
              disabled={!comparePreview}
              onClick={() => setPreviewMode("compare")}
              type="button"
            >
              View B
            </button>
            <RibbonMenu icon={Film} label="Film">
              <div className="grid gap-3">
                <SelectField icon={Film} label="Stock" value={project.filmId} onChange={setFilm}>
                  {filmPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                </SelectField>
                <div className="text-sm text-[color:var(--color-text-soft)]">{film.description}</div>
                <DetailGrid
                  items={[
                    { label: "ISO", value: String(film.iso) },
                    { label: "Contrast", value: film.contrast.toFixed(2) },
                    { label: "Saturation", value: film.saturation.toFixed(2) },
                    { label: "Grain", value: film.grain.toFixed(2) },
                    { label: "Halation", value: film.halation.toFixed(2) },
                    { label: "Warmth", value: film.warmth.toFixed(2) },
                  ]}
                />
              </div>
            </RibbonMenu>
            <RibbonMenu icon={Camera} label="Capture">
              <div className="grid gap-3">
                <SelectField icon={Camera} label="Camera" value={project.cameraId} onChange={setCamera}>
                  {cameraPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                </SelectField>
                <DetailGrid
                  items={[
                    { label: "Format", value: camera.format },
                    { label: "Format weight", value: camera.formatWeight.toFixed(2) },
                    { label: "Edge falloff", value: camera.edgeFalloff.toFixed(2) },
                  ]}
                />
                <SelectField icon={CircleDot} label="Lens" value={project.lensId} onChange={setLens}>
                  {lensPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.name}
                    </option>
                  ))}
                </SelectField>
                <DetailGrid
                  items={[
                    { label: "Focal length", value: lens.focalLength },
                    { label: "Bloom", value: lens.bloom.toFixed(2) },
                    { label: "Vignette", value: lens.vignette.toFixed(2) },
                    { label: "Halation bias", value: lens.halationBias.toFixed(2) },
                  ]}
                />
              </div>
            </RibbonMenu>
            <RibbonMenu icon={SplitSquareHorizontal} label="Snapshots">
              <div className="grid gap-2">
                {project.snapshots.length === 0 ? (
                  <div className="text-sm text-[color:var(--color-text-soft)]">No snapshots</div>
                ) : (
                  project.snapshots.map((snapshot) => (
                    <div key={snapshot.id} className="border border-[color:var(--color-border)] p-2">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <div>
                          <div className="text-sm">{snapshot.name}</div>
                          <div className="text-xs text-[color:var(--color-text-soft)]">
                            {filmPresetMap.get(snapshot.filmId)?.name ?? snapshot.filmId}
                          </div>
                        </div>
                        <button
                          className="icon-button p-2 text-[color:var(--color-danger)]"
                          onClick={() => removeSnapshot(snapshot.id)}
                          type="button"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                      <div className="flex gap-2">
                        <button
                          className="icon-button px-2 py-1 text-xs"
                          onClick={() => {
                            loadSnapshot(snapshot.id);
                            setPreviewMode("edited");
                          }}
                          type="button"
                        >
                          Load A
                        </button>
                        <button
                          className="icon-button px-2 py-1 text-xs"
                          onClick={() => {
                            setCompareSnapshot(
                              project.compareSnapshotId === snapshot.id ? null : snapshot.id,
                            );
                            setPreviewMode("compare");
                          }}
                          type="button"
                        >
                          {project.compareSnapshotId === snapshot.id ? "Clear B" : "Set B"}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </RibbonMenu>
            <RibbonMenu icon={Sparkles} label="Accidents">
              <div className="grid gap-3">
                <button
                  className="icon-button inline-flex items-center justify-center gap-2 px-3 py-2 text-sm"
                  onClick={randomizeAccidents}
                  type="button"
                >
                  <RefreshCcw className="h-4 w-4" />
                  <span>Randomize</span>
                </button>
                <QuickSlider
                  label="Light leak"
                  value={project.development.lightLeak}
                  min={0}
                  max={0.5}
                  step={0.01}
                  display={project.development.lightLeak.toFixed(2)}
                  defaultValue={defaultProject.development.lightLeak}
                  onChange={(value) => updateDevelopment({ lightLeak: Number(value.toFixed(2)) })}
                />
                <QuickSlider
                  label="Dust"
                  value={project.development.dust}
                  min={0}
                  max={0.5}
                  step={0.01}
                  display={project.development.dust.toFixed(2)}
                  defaultValue={defaultProject.development.dust}
                  onChange={(value) => updateDevelopment({ dust: Number(value.toFixed(2)) })}
                />
                <QuickSlider
                  label="Scratches"
                  value={project.development.scratches}
                  min={0}
                  max={0.5}
                  step={0.01}
                  display={project.development.scratches.toFixed(2)}
                  defaultValue={defaultProject.development.scratches}
                  onChange={(value) => updateDevelopment({ scratches: Number(value.toFixed(2)) })}
                />
                <QuickSlider
                  label="Drag"
                  value={project.development.drag}
                  min={0}
                  max={0.5}
                  step={0.01}
                  display={project.development.drag.toFixed(2)}
                  defaultValue={defaultProject.development.drag}
                  onChange={(value) => updateDevelopment({ drag: Number(value.toFixed(2)) })}
                />
              </div>
            </RibbonMenu>
            <RibbonMenu icon={Images} label="Frames">
              <div className="grid gap-3">
                {project.exposures.length === 0 ? (
                  <div className="text-sm text-[color:var(--color-text-soft)]">No frames</div>
                ) : (
                  project.exposures.map((exposure) => (
                    <div key={exposure.id} className="border border-[color:var(--color-border)] p-2">
                      <div className="mb-2 flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="truncate text-sm">{exposure.name}</div>
                          <div className="text-xs text-[color:var(--color-text-soft)]">
                            {exposure.loaded ? `${exposure.width}×${exposure.height}` : "loading"}
                          </div>
                        </div>
                        <div className="flex gap-1">
                          <button
                            className="icon-button p-2"
                            onClick={() => moveExposure(exposure.id, -1)}
                            type="button"
                          >
                            <ChevronUp className="h-4 w-4" />
                          </button>
                          <button
                            className="icon-button p-2"
                            onClick={() => moveExposure(exposure.id, 1)}
                            type="button"
                          >
                            <ChevronDown className="h-4 w-4" />
                          </button>
                          <button
                            className="icon-button p-2 text-[color:var(--color-danger)]"
                            onClick={() => removeExposure(exposure.id)}
                            type="button"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                      <QuickSlider
                        label="Weight"
                        value={exposure.weight}
                        min={0.4}
                        max={1.6}
                        step={0.1}
                        display={`${exposure.weight.toFixed(1)}x`}
                        defaultValue={1}
                        onChange={(value) => updateExposure(exposure.id, { weight: Number(value.toFixed(1)) })}
                      />
                      <QuickSlider
                        label="Offset X"
                        value={exposure.offsetX}
                        min={-0.35}
                        max={0.35}
                        step={0.01}
                        display={exposure.offsetX.toFixed(2)}
                        defaultValue={0}
                        onChange={(value) => updateExposure(exposure.id, { offsetX: Number(value.toFixed(2)) })}
                      />
                      <QuickSlider
                        label="Offset Y"
                        value={exposure.offsetY}
                        min={-0.35}
                        max={0.35}
                        step={0.01}
                        display={exposure.offsetY.toFixed(2)}
                        defaultValue={0}
                        onChange={(value) => updateExposure(exposure.id, { offsetY: Number(value.toFixed(2)) })}
                      />
                      <QuickSlider
                        label="Rotation"
                        value={exposure.rotation}
                        min={-12}
                        max={12}
                        step={0.5}
                        display={`${exposure.rotation.toFixed(1)}°`}
                        defaultValue={0}
                        onChange={(value) => updateExposure(exposure.id, { rotation: Number(value.toFixed(1)) })}
                      />
                    </div>
                  ))
                )}
              </div>
            </RibbonMenu>
          </div>
        </header>

        <main className="relative flex min-h-0 flex-1 bg-[color:var(--color-bg)]">
          <div className="flex min-h-0 flex-1 items-center justify-center bg-black px-4 py-4">
            {previewImageUrl ? (
              <div
                className="relative flex h-full w-full items-center justify-center"
                onContextMenu={(event) => event.preventDefault()}
                onMouseDown={beginCompareHold}
                onMouseLeave={endCompareHold}
                onMouseUp={endCompareHold}
                onTouchCancel={endCompareHold}
                onTouchEnd={endCompareHold}
                onTouchStart={beginCompareHold}
              >
                <img
                  className="max-h-full w-full object-contain"
                  src={previewImageUrl}
                  alt={`${project.title} preview`}
                />
                {compareSourceUrl && (
                  <>
                    <div className="pointer-events-none absolute left-3 top-3 border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1 text-xs text-[color:var(--color-text-soft)]">
                      {previewLabel}
                    </div>
                    <div className="pointer-events-none absolute bottom-3 left-3 border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1 text-xs text-[color:var(--color-text-soft)]">
                      Long press for original
                    </div>
                  </>
                )}
              </div>
            ) : (
              <label className="flex cursor-pointer flex-col items-center gap-2 border border-dashed border-[color:var(--color-border-strong)] px-5 py-8 text-center text-[color:var(--color-text-soft)]">
                <ImagePlus className="h-7 w-7" />
                <span className="text-sm">Add frames</span>
                <input
                  className="sr-only"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/tiff,.tif,.tiff"
                  multiple
                  onChange={(event) => {
                    if (event.target.files?.length) {
                      void importExposures(event.target.files);
                      event.target.value = "";
                    }
                  }}
                />
              </label>
            )}
          </div>

          <aside className="absolute right-4 top-4 w-[280px] border border-[color:var(--color-border)] bg-[color:var(--color-panel)] p-3 shadow-[0_16px_40px_rgba(0,0,0,0.35)]">
            <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-[0.12em] text-[color:var(--color-text-soft)]">
              <span>Quick Tools</span>
              <span>{loadedFrames} frames</span>
            </div>
            <div className="grid gap-3">
              <SelectField icon={Film} label="Film" value={project.filmId} onChange={setFilm}>
                {filmPresets.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </SelectField>
              <div className="grid grid-cols-2 gap-2">
                <label className="grid gap-1">
                  <span className="text-xs uppercase tracking-[0.12em] text-[color:var(--color-text-soft)]">ISO</span>
                  <input
                    className="control px-3 py-2"
                    type="number"
                    min={50}
                    max={6400}
                    step={50}
                    value={project.settings.iso}
                    onChange={(event) => updateSettings({ iso: Number(event.target.value) || 50 })}
                  />
                </label>
                <label className="grid gap-1">
                  <span className="text-xs uppercase tracking-[0.12em] text-[color:var(--color-text-soft)]">EV</span>
                  <input
                    className="control px-3 py-2"
                    type="number"
                    min={-3}
                    max={3}
                    step={0.1}
                    value={project.settings.exposureComp}
                    onChange={(event) => updateSettings({ exposureComp: Number(event.target.value) || 0 })}
                  />
                </label>
              </div>
              <QuickSlider
                label="Grain"
                value={project.development.grain}
                min={0}
                max={1}
                step={0.01}
                display={project.development.grain.toFixed(2)}
                defaultValue={defaultProject.development.grain}
                onChange={(value) => updateDevelopment({ grain: Number(value.toFixed(2)) })}
              />
              <QuickSlider
                label="Contrast"
                value={project.development.contrast}
                min={0}
                max={1}
                step={0.01}
                display={project.development.contrast.toFixed(2)}
                defaultValue={defaultProject.development.contrast}
                onChange={(value) => updateDevelopment({ contrast: Number(value.toFixed(2)) })}
              />
              <QuickSlider
                label="Saturation"
                value={project.development.saturation}
                min={0}
                max={1}
                step={0.01}
                display={project.development.saturation.toFixed(2)}
                defaultValue={defaultProject.development.saturation}
                onChange={(value) => updateDevelopment({ saturation: Number(value.toFixed(2)) })}
              />
              {selectedExposure && (
                <>
                  <div className="border-t border-[color:var(--color-border)] pt-3 text-xs uppercase tracking-[0.12em] text-[color:var(--color-text-soft)]">
                    Active frame
                  </div>
                  <QuickSlider
                    label="Weight"
                    value={selectedExposure.weight}
                    min={0.4}
                    max={1.6}
                    step={0.1}
                    display={`${selectedExposure.weight.toFixed(1)}x`}
                    defaultValue={1}
                    onChange={(value) =>
                      updateExposure(selectedExposure.id, { weight: Number(value.toFixed(1)) })
                    }
                  />
                  <QuickSlider
                    label="Rotation"
                    value={selectedExposure.rotation}
                    min={-12}
                    max={12}
                    step={0.5}
                    display={`${selectedExposure.rotation.toFixed(1)}°`}
                    defaultValue={0}
                    onChange={(value) =>
                      updateExposure(selectedExposure.id, { rotation: Number(value.toFixed(1)) })
                    }
                  />
                </>
              )}
            </div>
          </aside>

          <div className="absolute bottom-4 left-4 flex flex-wrap gap-2 text-xs text-[color:var(--color-text-soft)]">
            <div className="border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1">
              {renderStatus}
            </div>
            <div className="border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1">
              {activePreview ? `${activePreview.renderMs} ms` : "no preview"}
            </div>
            <div className="border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1">
              {camera.name}
            </div>
            <div className="border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1">
              {lens.name}
            </div>
          </div>

          {(renderError || exportError) && (
            <div className="absolute bottom-4 right-4 border border-[color:var(--color-danger)]/40 bg-[color:var(--color-danger)]/8 px-3 py-2 text-sm text-[color:var(--color-danger)]">
              {renderError ?? exportError}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
