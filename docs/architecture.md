# Architecture

## UI layer

- `src/App.tsx`
  - route table
- `src/components/LabLayout.tsx`
  - app shell
  - progress navigation
  - summary sidebar
  - live preview panel
- `src/routes/*`
  - one screen per workflow step

## State layer

- `src/store/filmLab.tsx`
  - central project state
  - persistence to `localStorage`
  - worker lifecycle
  - import/export orchestration
  - preview render scheduling

## Render layer

- `src/workers/pipeline.worker.ts`
  - file decode
  - scaled exposure storage
  - CPU render pipeline
  - preview and export jobs

## Performance strategy

- never decode and process uploads on the main thread
- keep a scaled working representation of each exposure in worker memory
- render preview proxies around `~1480px` max dimension
- render exports around `~3200px` max dimension
- debounce preview rerenders during slider movement

## Why the Python scripts stay

They are the best place to test:

- stronger stock presets
- black-and-white behavior
- staged film process ideas

The browser app is the product shell; the Python scripts remain the research bench.
