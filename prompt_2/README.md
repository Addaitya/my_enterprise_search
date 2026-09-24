# Agent memory

`prompt_2/` is agent memory. `prompts/` is a frozen archive of the original notes. Do not edit, move, or delete anything under `prompts/`.

Agents start at `current.md` before changing product behavior. `context/` holds the shipped decisions, APIs, and landmines distilled from `prompts/`. `index.md` maps each frozen file to one of those notes. Open one archived file only when you need the original why or how.

Humans use the root `README.md` for clone, setup, and stack. When product behavior changes, update `prompt_2/current.md` and the root `README.md` together.

Cursor injects `.cursor/rules/memory.mdc` on every Agent chat. `.cursor/rules/prompts-are-cold.mdc` applies when a file under `prompts/` is open.
