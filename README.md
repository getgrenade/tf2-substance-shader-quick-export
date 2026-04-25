# TF2 Substance Shader Export Plugin

**Install**
1. Copy `TF2_Paint.spexp` → `<Substance install>\resources\starter_assets\export-presets\`
2. Copy `tf2_export.py` → `Documents\Adobe\Adobe Substance 3D Painter\python\plugins\`
3. Load it in **Python > Plugin Manager**

**Four toolbar buttons**
- ☰ **Settings** — pick which texture sets to export, set a custom output path
- [R/B] **Toggle Red/Blue** — toggles visibility of any layers/folders with `_red` or `_blue` in their name. Works on both folders and individual layers
- ↓ **Export** — exports diffuse/normal at 512, expmask at 256 as TGA 8-bit
- ↓[B] **Export Blue** — exports current diffuse as `_diffuse_blue` without overwriting original

**Export path**
Project must be in a `bakes` folder — exports go to the sibling `texture` folder automatically. If not, you'll be prompted to set a custom path in settings.

**Note:** Settings reset on Substance restart. Toolbar is on the right. You need tf2 substance shader files for it to work.
