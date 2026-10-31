# datasheets/ — copied component diagrams

The schematic editor draws a component's diagram from this folder:

- **`<COMP_TYPE>.png` exists** → the canvas shows the datasheet's own
  diagram image (fitted inside the symbol's declared extent; pins, labels
  and wiring geometry stay exactly as declared in
  `ui/schematic_symbols.py`).
- **no file** → the symbol falls back to a plain square with the pins
  along its edges (and dedicated hand-drawn shapes for the built-in
  passives/semiconductors).

`<COMP_TYPE>` is the symbol key (`ESP32S3`, `ARDUINO_UNO`, …).

## Copying an image out of a datasheet

```powershell
python tools\extract_datasheet_img.py path\to\part.pdf --prefix ESP32S3
```

- Writes `datasheets\ESP32S3.png` (largest image on the page by default;
  `--page`/`--index` to choose another).
- Never modifies the PDF; exit 1 with a message when the PDF has no
  extractable images — the editor then keeps the generic symbol.
- Requires the pinned `pypdf` + Pillow already in `requirements.txt`.

Commit **PNGs only**: the 5 MB tracked-file rule applies (scorecard R11),
and datasheet PDFs are vendor documents you keep outside the repo.
