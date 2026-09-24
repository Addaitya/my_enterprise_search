# Agent memory

`prompt_2/` is agent memory. `prompts/` is a frozen archive of the original notes. Do not edit, move, or delete anything under `prompts/`.

Agents start at `current.md` before changing product behavior. `index.md` catalogs the frozen `prompts/` files. Open one archived file only when you need why or how something was built.

Humans use the root `README.md` for clone, setup, and stack. When product behavior changes, update `prompt_2/current.md` and the root `README.md` together.

Cursor injects `.cursor/rules/memory.mdc` on every Agent chat. `.cursor/rules/prompts-are-cold.mdc` applies when a file under `prompts/` is open.
