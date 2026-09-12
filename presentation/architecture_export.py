import os, pathlib
from playwright.sync_api import sync_playwright
src = pathlib.Path('docs/architecture.html').resolve()
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for out, scale in [('docs/architecture.png', 2), ('docs/architecture@1x.png', 1)]:
        pg = b.new_page(viewport={'width': 1560, 'height': 1100}, device_scale_factor=scale)
        pg.goto(src.as_uri())
        pg.wait_for_function("document.fonts.ready.then(()=>true)")
        pg.wait_for_timeout(1200)
        el = pg.query_selector('svg.diagram')
        el.screenshot(path=out, omit_background=True)
        box = el.bounding_box()
        print(f"{out}  {os.path.getsize(out):,} bytes  {int(box['width']*scale)}x{int(box['height']*scale)} px")
        pg.close()
    b.close()
