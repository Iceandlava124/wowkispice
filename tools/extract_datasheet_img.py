"""
extract_datasheet_img.py - copy a component's diagram image out of its
datasheet PDF into the repo so the schematic editor can draw it.

The editor looks for datasheets/<COMP_TYPE>.png (ui/schematic_items.py):
when that file exists, the symbol body is the datasheet's own diagram;
otherwise the symbol falls back to a plain square with pins along its
edges. This tool performs the "copy" step - it never modifies the PDF.

Usage:
    python tools/extract_datasheet_img.py path/to/part.pdf
    python tools/extract_datasheet_img.py part.pdf --prefix ESP32S3
    python tools/extract_datasheet_img.py part.pdf --page 2 -o datasheets

Images are written as PNG (converted via Pillow when the embedded format is
something else). By default the largest image on the selected page wins,
because datasheet pinout figures are almost always the biggest artwork on
the page; --index picks a specific one instead.

Exit codes: 0 at least one image copied, 1 no images found / unreadable PDF.
"""
import argparse
import os
import sys

from pypdf import PdfReader


def extract_images(pdf_path, out_dir, page=None, index=None, prefix=None):
    """Copy embedded images out of `pdf_path` into `out_dir`.

    Returns the list of written file paths (PNG). `page` limits to one
    0-based page, `index` picks one image on that page instead of the
    largest, `prefix` names the first saved image <prefix>.png (the
    editor's datasheet convention).
    """
    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        # Datasheets are not password-protected in practice; say so instead
        # of silently producing nothing.
        raise ValueError("PDF is encrypted; decrypt it first")
    pages = [reader.pages[page]] if page is not None else list(reader.pages)

    os.makedirs(out_dir, exist_ok=True)
    written = []
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    for pno, pg in enumerate(pages):
        try:
            images = list(pg.images)
        except Exception as exc:            # corrupt page artwork
            print("  page %d: cannot list images (%s)" % (pno + 1, exc))
            continue
        if not images:
            continue
        # Largest first: the pinout/diagram is the biggest figure on a page.
        def area(im):
            try:
                return im.image.size[0] * im.image.size[1]
            except Exception:
                return 0
        order = sorted(range(len(images)), key=lambda i: -area(images[i]))
        if index is not None:
            order = [index] if 0 <= index < len(images) else []
        for i in order:
            if prefix and not written:
                name = "%s.png" % prefix
            else:
                name = "%s_p%d_%d.png" % (stem, pno + 1, i)
            try:
                pimg = images[i]
                pil = pimg.image
            except Exception as exc:
                print("  skip image p%d#%d: %s" % (pno + 1, i, exc))
                continue
            # Normalise so the editor's QImage loader always accepts it.
            if pil.mode not in ("RGB", "RGBA", "L"):
                pil = pil.convert("RGBA" if "A" in pil.mode else "RGB")
            out_path = os.path.join(out_dir, name)
            pil.save(out_path, format="PNG")
            written.append(out_path)
            print("  copied %s (%dx%d) <- %s page %d image %d"
                  % (out_path, pil.size[0], pil.size[1],
                     os.path.basename(pdf_path), pno + 1, i))
            if prefix and not written:
                break          # the type-named file is saved; stop here
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Copy diagram images from a datasheet PDF into "
                    "datasheets/ for the schematic editor to draw.")
    ap.add_argument("pdf", help="datasheet PDF file")
    ap.add_argument("-o", "--out-dir", default=None,
                    help="output directory (default: <repo>/datasheets)")
    ap.add_argument("--page", type=int, default=None,
                    help="0-based page index (default: every page)")
    ap.add_argument("--index", type=int, default=None,
                    help="0-based image index on the page (default: largest)")
    ap.add_argument("--prefix", default=None,
                    help="name the saved diagram <PREFIX>.png, matching the "
                         "editor's datasheets/<COMP_TYPE>.png convention")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.pdf):
        print("not a file: %s" % args.pdf)
        return 1
    out_dir = args.out_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "datasheets")
    try:
        written = extract_images(args.pdf, out_dir, page=args.page,
                                 index=args.index, prefix=args.prefix)
    except Exception as exc:
        print("cannot read %s: %s" % (args.pdf, exc))
        return 1
    if not written:
        print("no images found in %s - the editor will keep the generic "
              "square-with-pins symbol for this part" % args.pdf)
        return 1
    print("%d image(s) copied into %s" % (len(written), out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
