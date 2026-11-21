"""Render real label helper at legacy camera scales, including device pixels."""
from pathlib import Path
import pytest


@pytest.mark.parametrize('dpr', [1, 2])
def test_label_glyphs_remain_visible_at_extreme_zoom(dpr):
    playwright = pytest.importorskip('playwright.sync_api')
    source = (Path(__file__).parents[1] / 'src/fleet-label-paint.mjs').read_text()
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(device_scale_factor=dpr)
        page.set_content('<canvas style="width:300px;height:80px"></canvas>')
        page.add_script_tag(content=source.replace('export function', 'function'))
        rows = page.evaluate('''() => {
          const c=document.querySelector('canvas'),dpr=devicePixelRatio;
          c.width=300*dpr;c.height=80*dpr;const ctx=c.getContext('2d');
          return [1,.02,.005,.001,.0001,.000001].map(scale=>{
            ctx.setTransform(1,0,0,1,0,0);ctx.clearRect(0,0,c.width,c.height);
            ctx.setTransform(dpr*scale,0,0,dpr*scale,200*dpr,100*dpr);
            fleetLabelTransform(ctx,scale);
            paintFleetLabel(ctx,{x:10,y:10,w:150,h:24,font:12,lines:['Agent label'],alpha:1,node:{}});
            const pixels=ctx.getImageData(0,0,c.width,c.height).data;
            let glyphs=0;for(let i=0;i<pixels.length;i+=4)if(pixels[i]>150&&pixels[i+1]>150&&pixels[i+2]>150)glyphs++;
            return {scale,font:ctx.font,glyphs};
          });
        }''')
        assert all('12px' in row['font'] for row in rows)
        assert rows[0]['glyphs'] > 50
        assert all(row['glyphs'] == rows[0]['glyphs'] for row in rows)
        browser.close()
