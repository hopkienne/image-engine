import html
import ipaddress
import random
import re
import socket
import time
from urllib.parse import urlsplit, quote, unquote
import requests
from .common import *

DEV=[('Nikon','D7000',3),('Nikon','D300',2),('Canon','EOS 300D',2),('Canon','EOS 10D',2),
     ('Canon','PowerShot S100',2),('Pentax','K10D',2),('Pentax','K-x',2),('Panasonic','DMC-GF1',3),
     ('Panasonic','DMC-LX7',2),('Sony','NEX-5N',1),('Sony','DSLR-A100',1),('Olympus','XZ-10',1),
     ('Olympus','E-410',1),('Fujifilm','X-E1',1),('Fujifilm','X-A1',1),('Leica','D-LUX 5',2)]
HOLD=[('Nikon','D700',2),('Pentax','K200D',2),('Panasonic','DMC-G10',2),('Canon','PowerShot G1 X',2),
      ('Sony','NEX-C3',1),('Olympus','E-500',1),('Fujifilm','X-M1',1),('Fujifilm','FinePix X100',1)]
PILOT_MODELS={('Nikon','D7000'),('Canon','EOS 300D'),('Canon','EOS 10D'),('Canon','PowerShot S100'),
              ('Pentax','K10D'),('Pentax','K-x'),('Panasonic','DMC-GF1'),('Panasonic','DMC-LX7'),
              ('Sony','NEX-5N'),('Olympus','XZ-10'),('Fujifilm','X-E1'),('Leica','D-LUX 5')}

def plan():
    path=RUN/'corpus.manifest.json'
    if path.exists(): return load(path)
    rows=load(BASE/'reference/raw-repository.json')['data']
    rng=random.Random(20260930); items=[]; seen=set()
    existing={sha(p):p for p in (ROOT/'fixtures/raw').rglob('*') if p.is_file() and p.suffix.lower() in ('.nef','.orf','.dng')}
    for split,groups in [('development',DEV),('holdout',HOLD)]:
        for make,model,n in groups:
            candidates=[r for r in rows if r[:2]==[make,model] and 'https://creativecommons.org/publicdomain/zero/1.0/' in r[5]
                        and not re.search(r'sraw|mraw|pixel.?shift|mono|linear|hdr',r[2],re.I)]
            candidates.sort(key=lambda r: r[7]); rng.shuffle(candidates)
            # Prefer an existing byte-identical fixture after current per-file license verification.
            candidates.sort(key=lambda r: 0 if re.search(r'[0-9a-f]{64}',r[7]).group() in existing else 1)
            if len(candidates)<n: raise RuntimeError(f'BLOCKED selection {make}/{model}: only {len(candidates)} usable entries')
            chosen=0
            for r in candidates:
                expected=re.search(r'[0-9a-f]{64}',r[7]).group()
                if expected in seen: continue
                seen.add(expected)
                url=html.unescape(re.search(r"href='([^']+)'",r[7]).group(1))
                rid=re.search(r'getfile.php/(\d+)/',url).group(1)
                extension=Path(unquote(urlsplit(url).path)).suffix.lower()
                item={'source_id':f'R{len(items)+1:03d}','publisher_id':rid,'make':make,'model':model,
                      'publisher_subtype':r[2],'publisher_megapixels':r[3],
                      'publisher_remark':r[4],'license_id':'CC0-1.0',
                      'license_url':'https://creativecommons.org/publicdomain/zero/1.0/',
                      'license_evidence':r[5], 'repository_evidence_sha256':sha(BASE/'reference/raw-repository.json'),
                      'landing_url':'https://raw.pixls.us/','direct_url':quote(url,safe=':/%'),
                      'publisher_sha256':expected,'sha256':None,'bytes':None,'accessed_at':now(),
                      'split':split,'scene_session_group':f'unknown-session:{make}:{model}',
                      'group_evidence':'Conservative: all variants of same camera/model kept together because sessions unknown.',
                      'scene_tags':[], 'scene_tag_evidence':None,'illuminant':None,'portrait':None,
                      'cfa':None,'iso':None,'acquisition_status':'NOT_RUN',
                      'path':f'corpus/originals/R{len(items)+1:03d}{extension}',
                      'pilot':split=='development' and (make,model) in PILOT_MODELS and chosen==0,
                      'local_verified_fixture':str(existing[expected]) if expected in existing else None,
                      'publisher_row':r}
                items.append(item); chosen+=1
                if chosen==n: break
    manifest={'created_at':now(),'scope_status':'Proposed','seed':20260930,
              'selection_before_pixel_review':True,'planned_total':40,'planned_pilot':12,
              'development':28,'holdout':12,'items':items,
              'coverage_gaps':['scene/illuminant/portrait/low-light labels unverified',
                               'no valid measured chart reference','no production camera certification']}
    assert len(items)==40 and sum(v['pilot'] for v in items)==12
    write(path,manifest)
    write(RUN/'selection.lock.json',{'created_at':now(),'manifest_sha256':sha(path),
          'immutable_selection_digest':digest([{k:v[k] for k in ('source_id','publisher_sha256','split','scene_session_group','pilot')} for v in items]),
          'rationale':'Fixed low/medium-resolution CC0 multi-brand Bayer and exploratory Fuji samples, selected before inspecting rendered pixels. MP limits checked against actual probe.'})
    write(RUN/'source_registry.json',{'raw_pixls_us':{'status':'PER_FILE_CC0_VERIFIED','snapshot':str(BASE/'reference/raw-repository.json'),
          'snapshot_sha256':sha(BASE/'reference/raw-repository.json'),'items':len(items)},
          'fivek':{'status':'PENDING_LICENSE_REVIEW','downloaded':False}})
    return manifest

def validate_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname!='raw.pixls.us' or u.username or u.password or u.port not in (None,443):
        raise ValueError('BLOCKED unapproved acquisition URL')
    for info in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError('BLOCKED private/nonpublic destination')

def stream_checked(chunks, target, expected, file_limit, remaining, deadline=None):
    """Enforce actual bytes, even when Content-Length is absent or false."""
    h=hashlib.sha256(); count=0
    try:
        with target.open('wb') as f:
            for chunk in chunks:
                if deadline and time.monotonic()>deadline: raise TimeoutError('download attempt deadline')
                count+=len(chunk)
                if count>min(file_limit,remaining): raise ValueError('download stream quota exceeded')
                h.update(chunk); f.write(chunk)
        if h.hexdigest()!=expected: raise ValueError('publisher SHA256 mismatch')
        return count
    except Exception:
        target.unlink(missing_ok=True)
        raise

def acquire(item):
    path=RUN/item['path']; path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and sha(path)==item['publisher_sha256']:
        return dict(item,sha256=sha(path),bytes=path.stat().st_size,acquisition_status='SUCCESS',acquisition_cache_hit=True)
    p=load(BASE/'benchmark.policy.json')['acquisition']; budget(p['max_raw_file_bytes'])
    ledger_path=RUN/'downloads.json'; ledger=load(ledger_path) if ledger_path.exists() else {'downloaded_bytes':0,'attempts':[]}
    remaining=p['max_download_bytes_total']-ledger['downloaded_bytes']; attempts=[]
    if item['local_verified_fixture']:
        shutil.copyfile(item['local_verified_fixture'],path)
        if sha(path)!=item['publisher_sha256']: raise ValueError('local fixture hash changed')
        return dict(item,sha256=sha(path),bytes=path.stat().st_size,acquisition_status='SUCCESS',acquisition_method='byte-identical existing fixture; current per-file CC0 evidence')
    for attempt in range(p['max_retries']+1):
        time.sleep(p['minimum_request_interval_seconds'])
        start=time.monotonic(); temp=path.with_suffix(path.suffix+'.part'); actual=0
        try:
            url=item['direct_url']; redirects=[]
            for _ in range(6):
                validate_url(url)
                response=requests.get(url,stream=True,allow_redirects=False,timeout=(20,90))
                if response.is_redirect:
                    from urllib.parse import urljoin
                    next_url=urljoin(url,response.headers['Location']); redirects.append(next_url); response.close(); url=next_url
                else: break
            else: raise ValueError('too many redirects')
            response.raise_for_status()
            length=response.headers.get('Content-Length')
            if length and int(length)>min(p['max_raw_file_bytes'],remaining): raise ValueError('header exceeds quota')
            def counted_chunks():
                nonlocal actual
                for chunk in response.iter_content(256*1024):
                    actual+=len(chunk); yield chunk
            with response:
                size=stream_checked(counted_chunks(),temp,item['publisher_sha256'],p['max_raw_file_bytes'],remaining,start+360)
            attempts.append({'attempt':attempt+1,'status':'SUCCESS','bytes':actual,'seconds':time.monotonic()-start,'redirects':redirects})
            ledger['downloaded_bytes']+=actual; ledger['attempts'].append({'source_id':item['source_id'],**attempts[-1]}); write(ledger_path,ledger)
            temp.replace(path)
            return dict(item,sha256=sha(path),bytes=size,acquisition_status='SUCCESS',download_attempts=attempts)
        except Exception as exc:
            ledger['downloaded_bytes']+=actual; remaining-=actual
            temp.unlink(missing_ok=True)
            attempts.append({'attempt':attempt+1,'status':'FAILED','reason':str(exc),'bytes':actual})
            ledger['attempts'].append({'source_id':item['source_id'],**attempts[-1]}); write(ledger_path,ledger)
    return dict(item,acquisition_status='BLOCKED',reason='download failed after bounded retries',download_attempts=attempts)
