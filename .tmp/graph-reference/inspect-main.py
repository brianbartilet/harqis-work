import os,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts.deploy import load_env_into_os,load_machine_config,machine_env_vars
load_env_into_os();os.environ.update(machine_env_vars(load_machine_config(None)))
from dotenv import load_dotenv
load_dotenv(Path('frontend/.env'),override=True)
sys.path.insert(0,str(Path('frontend').resolve()))
from config import get_settings
from playwright.sync_api import sync_playwright
settings=get_settings()
with sync_playwright() as p:
 options={'headless':True}
 if not Path(p.chromium.executable_path).exists():options['channel']='msedge'
 browser=p.chromium.launch(**options)
 page=browser.new_page(viewport={'width':1440,'height':1000})
 page.goto('http://127.0.0.1:8093/login')
 page.locator('input[name=username]').fill(settings.app_username)
 page.locator('input[name=password]').fill(settings.app_password)
 page.locator('button[type=submit]').click()
 page.route('**/api/hfl/graph-views*',lambda r:r.fulfill(json={'views':[],'last_used':None}))
 page.add_init_script('''(()=>{const arc=CanvasRenderingContext2D.prototype.arc;window.centers=[];CanvasRenderingContext2D.prototype.arc=function(x,y,r,...args){const m=this.getTransform();if(this.canvas===document.querySelector('#kg-canvas canvas')&&Math.abs(r*m.a/devicePixelRatio-18)<.01){const p=new DOMPoint(x,y).matrixTransform(m);window.centers.push({x:p.x/devicePixelRatio,y:p.y/devicePixelRatio});window.centers=window.centers.slice(-30);}return arc.call(this,x,y,r,...args);};})();''')
 page.goto('http://127.0.0.1:8093/hfl-corpus/graph?example=1')
 page.wait_for_selector('#kg-workspace:not([inert])')
 page.wait_for_timeout(3500)
 page.screenshot(path='.tmp/graph-reference/original-before.png')
 box=page.locator('#kg-canvas canvas').first.bounding_box()
 candidates=page.evaluate('window.centers')
 grabbed=False
 for c in candidates:
  if not (40<c['x']<box['width']-40 and 40<c['y']<min(box['height']-40,950-box['y'])):continue
  x,y=box['x']+c['x'],box['y']+c['y']
  page.mouse.move(x,y);page.wait_for_timeout(300)
  if page.locator('#kg-canvas').evaluate('(e)=>e.style.cursor')=='pointer':
   page.mouse.down();page.mouse.move(x+60,y+40,steps=12);page.wait_for_timeout(200)
   page.screenshot(path='.tmp/graph-reference/original-drag.png')
   page.mouse.up();grabbed=True;break
 assert grabbed,'No draggable node located in reference canvas'
 page.wait_for_timeout(2000)
 page.screenshot(path='.tmp/graph-reference/original-after.png')
 print('Reference main frontend authenticated; original example graph dragged and screenshots captured.')
 browser.close()
