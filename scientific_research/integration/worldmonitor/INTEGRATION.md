# World Monitor / Finance Monitor integration

The supplied ZIPs contain `Panel.ts`, `components/index.ts`, `config/variants/finance.ts`, and `App.ts`, but **do not contain the current `PanelLayoutManager` implementation** that actually instantiates the panel grid. Because of that, the standalone SRB engine is fully compiled/tested, while the final panel registration must wait for that missing file to be patched safely.

## Files to copy

1. Copy this package's `src/` directory to your repo as `src/scientific-research/`.
2. Copy `ScientificResearchPanel.ts` to `src/components/ScientificResearchPanel.ts`.

## Known changes visible from the supplied archive

### `src/components/index.ts`
Add:

```ts
export * from './ScientificResearchPanel';
```

### `src/config/variants/finance.ts`
Inside `DEFAULT_PANELS`, add:

```ts
'scientific-research': {
  name: 'Scientific Research Brain',
  enabled: true,
  priority: 1,
},
```

Do the same in `full.ts` only if you want the panel in the full/global variant.

## Missing registration point

The supplied `App.ts` delegates panel creation to `PanelLayoutManager`. Add `ScientificResearchPanel` where that manager maps panel IDs to constructors, using the ID `scientific-research`.

Do **not** instantiate it in `App.ts` independently; that would bypass the existing layout/state lifecycle.

## LLM configuration

Phase 1 works without an LLM using a conservative deterministic compiler. For deeper extraction, pass an OpenAI-compatible endpoint such as the local Ollama/LM Studio endpoint already supported by the terminal. Do not persist the API key in research memory.

The wrapper deliberately does not read private runtime secrets itself because the provided archive does not expose a public secret getter contract suitable for this panel. Wire the existing runtime configuration into the panel constructor at the actual panel factory.
