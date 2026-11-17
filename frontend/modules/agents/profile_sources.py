"""Configurable metadata catalogs; exact-revision downloads live outside Git."""
import fnmatch
import hashlib
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import ssl
import time
from urllib.parse import quote, urlsplit
import uuid
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[3] / 'agents/prompts/agency'
MAX_FILE = 1024 * 1024
MAX_ARCHIVE = 32 * MAX_FILE
CONFIG = {'name', 'type', 'location', 'ref', 'paths', 'enabled'}


def store():
    from modules.agents.service import store as fleet_store
    return fleet_store()


def sha(content):
    return hashlib.sha256(content).hexdigest()


def public_url(url, resolve=True):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443) or parsed.fragment:
        raise ValueError('Use a public HTTPS URL without credentials, fragments or custom ports.')
    if not resolve:
        return url
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('Catalog downloads cannot access private or local network addresses.')
    except socket.gaierror:
        raise ValueError('Catalog host could not be resolved.') from None
    return url


def download(url, maximum=MAX_FILE):
    public_url(url,resolve=False)
    parsed=urlsplit(url)
    # Connect to the validated numeric address, retaining the hostname for TLS.
    # This avoids a second DNS resolution between address validation and connect.
    try:
        addresses=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError('Catalog downloads cannot access private or local network addresses.')
        class Connection(http.client.HTTPSConnection):
            def connect(self):
                sock=socket.create_connection((addresses[0][4][0],443),timeout=30)
                try:
                    self.sock=ssl.create_default_context().wrap_socket(sock,server_hostname=parsed.hostname)
                except Exception:
                    sock.close()
                    raise
        connection=Connection(parsed.hostname,timeout=30)
        try:
            connection.request('GET',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),headers={'User-Agent':'HARQIS-profile-catalog'})
            response=connection.getresponse()
            if response.status != 200:
                raise ValueError(f'Catalog download returned HTTP {response.status}. Check source settings and try again.')
            result = bytearray()
            started=time.monotonic()
            while chunk:=response.read(65536):
                result.extend(chunk)
                if len(result)>maximum or time.monotonic()-started>90:
                    raise ValueError('Catalog download exceeds its size or time limit.')
            return bytes(result)
        finally:
            connection.close()
    except (OSError,http.client.HTTPException):
        raise ValueError('Catalog download failed. Cached and saved profiles remain available.') from None


def local_path(location):
    path = Path(location).expanduser().resolve()
    roots = [Path(p).expanduser().resolve() for p in os.environ.get('HARQIS_PROFILE_SOURCE_ROOTS','').split(os.pathsep) if p]
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError('Local sources must be inside an administrator-configured HARQIS_PROFILE_SOURCE_ROOTS directory.')
    if not path.is_dir():
        raise ValueError('Local source directory is unavailable.')
    return path


def seed():
    manifest = json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
    source = {'id':'agency-agents','version':1,'name':'Agency Agents','type':'github',
              'location':'msitarzewski/agency-agents','ref':'main','enabled':True,
              'paths':[name+'/*.md' for name in json.loads((ROOT/'divisions.json').read_text(encoding='utf-8'))['divisions']],
              'revision':manifest['revision'],'last_sync':None,'error':'','count':len(manifest['profiles'])}
    with store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM fleet_profile_sources WHERE id=?',(source['id'],)).fetchone():
            return
        db.execute('INSERT INTO fleet_profile_sources VALUES (?,?,?)',(source['id'],1,json.dumps(source)))
        for row in manifest['profiles']:
            value = {**row,'id':source['id']+':'+row['id'],'slug':row['id'],'source':source['id'],
                     'source_name':source['name'],'revision':manifest['revision'],
                     'source_url':f"https://github.com/{source['location']}/blob/{manifest['revision']}/{row['path']}",
                     'download_url':f"https://raw.githubusercontent.com/{source['location']}/{manifest['revision']}/{row['path']}"}
            db.execute('INSERT INTO fleet_profile_index VALUES (?,?,?)',(source['id'],value['id'],json.dumps(value)))


def sources():
    seed()
    with store().connect() as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM fleet_profile_sources ORDER BY id')]


def get(identity):
    return next((row for row in sources() if row['id']==identity), None)


def save(raw, identity=None):
    if not isinstance(raw,dict) or set(raw)-CONFIG-{'version'}:
        raise ValueError('Choose supported profile source settings.')
    old = get(identity) if identity else None
    if identity and not old:
        raise ValueError('Profile source unavailable.')
    item={**(old or {}),**{k:v for k,v in raw.items() if k in CONFIG}}
    for key,maximum in [('name',120),('location',2000),('ref',200)]:
        if not isinstance(item.get(key),str) or len(item[key])>maximum or '\x00' in item[key]:
            raise ValueError('Invalid source '+key+'.')
        item[key]=item[key].strip()
    if not item['name'] or item.get('type') not in {'github','manifest','local'} or type(item.get('enabled')) is not bool:
        raise ValueError('Choose a source name, type and enabled state.')
    if not isinstance(item.get('paths'),list) or not 1<=len(item['paths'])<=50 or any(not isinstance(p,str) or not p or len(p)>300 or '..' in PurePosixPath(p).parts or p.startswith('/') for p in item['paths']):
        raise ValueError('Supply up to 50 relative include patterns.')
    if item['type']=='github':
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',item['location']) or not item['ref']:
            raise ValueError('Use owner/repository and a branch, tag or full commit.')
    elif item['type']=='manifest':
        public_url(item['location'])
    else:
        local_path(item['location'])
    item.update(id=identity or 'source-'+uuid.uuid4().hex,version=(old or {}).get('version',0)+1)
    changed=old and any(item[k]!=old[k] for k in ('type','location','ref','paths'))
    if not old or changed:
        item.update(revision='',last_sync=None,error='',count=0)
    with store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT version FROM fleet_profile_sources WHERE id=?',(item['id'],)).fetchone()
        if current and raw.get('version')!=current[0]:
            raise ValueError('Source changed. Reload before saving.')
        db.execute('INSERT OR REPLACE INTO fleet_profile_sources VALUES (?,?,?)',(item['id'],item['version'],json.dumps(item)))
        if changed:
            db.execute('DELETE FROM fleet_profile_index WHERE source=?',(identity,))
    return item


def remove(identity, version):
    if identity=='agency-agents':
        raise ValueError('Disable the default source instead of removing it.')
    with store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT version FROM fleet_profile_sources WHERE id=?',(identity,)).fetchone()
        if not row or row[0]!=version:
            raise ValueError('Source changed. Reload before removing it.')
        db.execute('DELETE FROM fleet_profile_index WHERE source=?',(identity,))
        db.execute('DELETE FROM fleet_profile_sources WHERE id=?',(identity,))
    return {'removed':True}


def catalog():
    enabled={s['id']:s for s in sources() if s['enabled']}
    with store().connect() as db:
        return [{**json.loads(row['payload']),'source_name':enabled[row['source']]['name']} for row in db.execute('SELECT * FROM fleet_profile_index ORDER BY rowid') if row['source'] in enabled]


def frontmatter(content):
    if len(content)>MAX_FILE:
        raise ValueError('Profile exceeds the 1 MB file limit.')
    text=content.decode('utf-8-sig')
    match=re.match(r'\A---\s*\n(.*?)\n---\s*\n',text,re.S)
    if not match:
        return None,text
    try:
        meta=yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise ValueError('Invalid profile frontmatter.') from None
    return meta,text[match.end():].strip()


def metadata(source, path, content, revision, divisions=None):
    meta,_=frontmatter(content)
    if not isinstance(meta,dict) or not isinstance(meta.get('name'),str) or not isinstance(meta.get('description'),str):
        return None
    if len(meta['name'])>200 or len(meta['description'])>3000:
        raise ValueError('Profile name or description is too long.')
    # Use full relative paths for custom sources to avoid duplicate filename collisions.
    slug=PurePosixPath(path).stem if source['id']=='agency-agents' else sha(path.encode())[:24]
    division=path.split('/')[0] if '/' in path else 'General'
    row=dict(id=source['id']+':'+slug,slug=slug,source=source['id'],source_name=source['name'],
             name=meta['name'],description=meta['description'],path=path,hash=sha(content),revision=revision,
             division=(divisions or {}).get(division,{}).get('label',division.replace('-',' ').title()),
             classification='coding' if division in {'engineering','testing','security','game-development','spatial-computing'} else 'general',skills=[])
    row['kind']='skill-package' if PurePosixPath(path).name=='SKILL.md' else 'profile'
    if source['id']=='agency-agents':
        row.update(json.loads((ROOT/'helpers.json').read_text(encoding='utf-8')).get(slug,{}))
    return row


def matches(source,path):
    return any(fnmatch.fnmatchcase(path,p) for p in source['paths'])


def github_links(source, row, revision):
    escaped=quote(row['path'],safe='/')
    return {**row,'revision':revision,
            'source_url':f"https://github.com/{source['location']}/blob/{revision}/{escaped}",
            'download_url':f"https://raw.githubusercontent.com/{source['location']}/{revision}/{escaped}"}


def github_changes(source,revision):
    """Reuse metadata for unchanged files; fall back to an archive for large/diverged diffs."""
    previous=source.get('revision','')
    if not re.fullmatch('[0-9a-f]{40}',previous):
        return None
    try:
        comparison=json.loads(download(f"https://api.github.com/repos/{source['location']}/compare/{previous}...{revision}",8*MAX_FILE))
    except ValueError:
        return None
    files=comparison.get('files',[])
    if comparison.get('status')!='ahead' or comparison.get('total_commits',0)>250 or len(files)>=300 or any(f['filename']=='divisions.json' for f in files):
        return None
    relevant=[f for f in files if matches(source,f['filename']) or matches(source,f.get('previous_filename',''))]
    if len(relevant)>40:
        return None
    with store().connect() as db:
        rows={row['path']:github_links(source,row,revision) for record in db.execute('SELECT payload FROM fleet_profile_index WHERE source=?',(source['id'],)) for row in [json.loads(record[0])]}
    divisions=json.loads((ROOT/'divisions.json').read_text(encoding='utf-8'))['divisions'] if source['id']=='agency-agents' else {}
    for change in relevant:
        path=change['filename']
        rows.pop(change.get('previous_filename',path),None)
        rows.pop(path,None)
        if change['status']=='removed' or not path.endswith('.md') or not matches(source,path):
            continue
        content=download(github_links(source,{'path':path},revision)['download_url'])
        row=metadata(source,path,content,revision,divisions)
        if row:
            rows[path]=github_links(source,row,revision)
    return list(rows.values())


def discover(source):
    rows=[]
    if source['type']=='github':
        info=json.loads(download(f"https://api.github.com/repos/{source['location']}/commits/{quote(source['ref'],safe='')}"))
        revision=info.get('sha','')
        if not re.fullmatch('[0-9a-f]{40}',revision):
            raise ValueError('GitHub did not return an immutable commit.')
        if revision==source.get('revision'):
            with store().connect() as db:
                return revision,[json.loads(row[0]) for row in db.execute('SELECT payload FROM fleet_profile_index WHERE source=? ORDER BY rowid',(source['id'],))]
        changed=github_changes(source,revision)
        if changed is not None:
            if len(changed)>5000 or len({r['id'] for r in changed})!=len(changed):
                raise ValueError('Catalog has duplicate IDs or exceeds 5,000 profiles.')
            return revision,changed
        archive=download(f"https://codeload.github.com/{source['location']}/zip/{revision}",MAX_ARCHIVE)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            members=package.infolist()
            if not members or len(members)>15000 or sum(m.file_size for m in members)>128*MAX_FILE:
                raise ValueError('Repository archive exceeds catalog discovery limits.')
            prefix=members[0].filename.split('/')[0]+'/'
            divisions={}
            if prefix+'divisions.json' in package.namelist():
                divisions=json.loads(package.read(prefix+'divisions.json')).get('divisions',{})
            for member in members:
                path=member.filename[len(prefix):]
                if not path.endswith('.md') or not matches(source,path):
                    continue
                if member.file_size>MAX_FILE:
                    raise ValueError('Profile exceeds the 1 MB file limit.')
                row=metadata(source,path,package.read(member),revision,divisions)
                if row:
                    rows.append(github_links(source,row,revision))
    elif source['type']=='local':
        root=local_path(source['location'])
        for path in root.rglob('*.md'):
            if not path.resolve().is_relative_to(root) or not matches(source,path.relative_to(root).as_posix()):
                continue
            if path.stat().st_size>MAX_FILE:
                raise ValueError('Profile exceeds the 1 MB file limit.')
            content=path.read_bytes()
            row=metadata(source,path.relative_to(root).as_posix(),content,sha(content))
            if row:
                rows.append(row)
            if len(rows)>5000:
                raise ValueError('Catalog exceeds 5,000 profiles.')
        revision=sha(json.dumps(rows,sort_keys=True).encode())
    else:
        manifest=json.loads(download(source['location'],8*MAX_FILE))
        if not isinstance(manifest,dict) or not isinstance(manifest.get('profiles'),list):
            raise ValueError('Catalog manifest needs a profiles array.')
        revision=manifest.get('revision')
        if not isinstance(revision,str) or not 1<=len(revision)<=200:
            raise ValueError('Catalog manifest needs a revision.')
        for item in manifest.get('profiles',[]):
            if not isinstance(item,dict) or any(not isinstance(item.get(k),str) or not item[k] for k in ('id','name','description','url','hash')):
                raise ValueError('Manifest profiles need id, name, description, url and SHA-256 hash.')
            if not re.fullmatch('[0-9a-f]{64}',item['hash']) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}',item['id']) or len(item['name'])>200 or len(item['description'])>3000:
                raise ValueError('Invalid manifest profile metadata.')
            public_url(item['url'],resolve=False)
            rows.append(dict(id=source['id']+':'+item['id'],slug=item['id'],source=source['id'],source_name=source['name'],
                             name=item['name'],description=item['description'],hash=item['hash'],revision=revision,
                             division=str(item.get('division','General'))[:120],classification=item.get('classification','general') if item.get('classification') in {'coding','general','workflows'} else 'general',
                             download_url=item['url'],source_url=item['url'],skills=[],kind='skill-package' if item.get('kind')=='skill-package' or PurePosixPath(urlsplit(item['url']).path).name=='SKILL.md' else 'profile'))
    if len(rows)>5000 or len({r['id'] for r in rows})!=len(rows):
        raise ValueError('Catalog has duplicate IDs or exceeds 5,000 profiles.')
    return revision,rows


def refresh(identity,version):
    source=get(identity)
    if not source or source['version']!=version:
        raise ValueError('Source changed. Reload before refreshing.')
    try:
        revision,rows=discover(source)
    except (ValueError,OSError,UnicodeError,zipfile.BadZipFile) as exc:
        message=str(exc) if isinstance(exc,ValueError) and not isinstance(exc,json.JSONDecodeError) else 'Source discovery failed. Check its settings and try again.'
        with store().connect() as db:
            source['error']=message
            db.execute('UPDATE fleet_profile_sources SET payload=? WHERE id=? AND version=?',(json.dumps(source),identity,version))
        raise ValueError(message) from None
    with store().connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT version FROM fleet_profile_sources WHERE id=?',(identity,)).fetchone()
        if not current or current[0]!=version:
            raise ValueError('Source changed during refresh. Reload and try again.')
        previous={row['id']:json.loads(row['payload'])['hash'] for row in db.execute('SELECT * FROM fleet_profile_index WHERE source=?',(identity,))}
        newer={row['id']:row['hash'] for row in rows}
        changes={'added':len(newer.keys()-previous.keys()),'removed':len(previous.keys()-newer.keys()),'changed':sum(previous[k]!=newer[k] for k in newer.keys() & previous.keys())}
        source.update(revision=revision,count=len(rows),last_sync=time.time(),error='',version=version+1,changes=changes)
        db.execute('DELETE FROM fleet_profile_index WHERE source=?',(identity,))
        db.executemany('INSERT INTO fleet_profile_index VALUES (?,?,?)',[(identity,row['id'],json.dumps(row)) for row in rows])
        db.execute('UPDATE fleet_profile_sources SET version=?,payload=? WHERE id=?',(source['version'],json.dumps(source),identity))
    return source


def body(row):
    with store().connect() as db:
        # Cached bodies are disposable; saved agent snapshots are independent.
        db.execute('DELETE FROM fleet_profile_cache WHERE accessed<?',(time.time()-30*86400,))
        hit=db.execute('SELECT content FROM fleet_profile_cache WHERE hash=?',(row['hash'],)).fetchone()
        if hit and sha(bytes(hit[0]))==row['hash']:
            db.execute('UPDATE fleet_profile_cache SET accessed=? WHERE hash=?',(time.time(),row['hash']))
            return bytes(hit[0])
    source=get(row['source'])
    if not source or not source['enabled']:
        raise ValueError('Profile source is disabled or unavailable.')
    if source['type']=='local':
        root=local_path(source['location'])
        path=(root/row['path']).resolve()
        try:
            if not path.is_relative_to(root) or path.stat().st_size>MAX_FILE:
                raise ValueError('Profile path is outside its source or exceeds the file limit.')
            content=path.read_bytes()
        except OSError:
            raise ValueError('Profile file is unavailable. Refresh the source; saved agents remain usable.') from None
    else:
        content=download(row['download_url'])
    if sha(content)!=row['hash']:
        raise ValueError('Profile changed upstream or failed its integrity check. Refresh the source and review the new version.')
    with store().connect() as db:
        db.execute('INSERT OR REPLACE INTO fleet_profile_cache VALUES (?,?,?)',(row['hash'],content,time.time()))
        size=db.execute('SELECT coalesce(sum(length(content)),0) FROM fleet_profile_cache').fetchone()[0]
        if size>64*MAX_FILE:
            for cached in db.execute('SELECT hash,length(content) AS size FROM fleet_profile_cache ORDER BY accessed').fetchall():
                if size<=64*MAX_FILE:
                    break
                db.execute('DELETE FROM fleet_profile_cache WHERE hash=?',(cached['hash'],))
                size-=cached['size']
    return content
