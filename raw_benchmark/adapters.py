import configparser
import struct
import xml.etree.ElementTree as ET
from .common import *
from .imaging import normalize, measurements, read_native, effect
from .smoke import dt_argv
import tifffile

DT='{http://darktable.sf.net/}'
for prefix, uri in [('x','adobe:ns:meta/'),('rdf','http://www.w3.org/1999/02/22-rdf-syntax-ns#'),
                    ('darktable','http://darktable.sf.net/'),('xmp','http://ns.adobe.com/xap/1.0/'),
                    ('xmpMM','http://ns.adobe.com/xap/1.0/mm/')]:
    ET.register_namespace(prefix,uri)
ALLOWED={'rawprepare','demosaic','colorin','colorout','gamma','temperature','flip','exposure','invert'}

def dt_control(generated,output,wb_red_factor=1.0):
    tree=ET.parse(generated); history=[]
    for node in tree.iter():
        operation=node.attrib.get(DT+'operation')
        if operation is None: continue
        if operation not in ALLOWED: node.attrib[DT+'enabled']='0'
        if operation=='temperature' and wb_red_factor!=1:
            if node.attrib[DT+'modversion']!='4': raise ValueError('BLOCKED: unknown WB module layout')
            raw=bytes.fromhex(node.attrib[DT+'params'])
            if len(raw)!=20: raise ValueError('BLOCKED: WB params size contradicts source version 4')
            red,green,blue,various,preset=struct.unpack('<ffffi',raw)
            node.attrib[DT+'params']=struct.pack('<ffffi',red*wb_red_factor,green,blue,various,preset).hex()
        if operation=='exposure' and node.attrib.get(DT+'enabled')=='1':
            raw=node.attrib[DT+'params']
            if node.attrib[DT+'modversion']!='7' or raw.startswith('gz') or len(bytes.fromhex(raw))!=28:
                raise ValueError('BLOCKED: cannot verify active exposure params')
            values=list(struct.unpack('<iffffii',bytes.fromhex(raw)))
            values[0]=0; values[1]=0.; values[2]=0.; values[5]=0; values[6]=0
            node.attrib[DT+'params']=struct.pack('<iffffii',*values).hex()
        history.append({'operation':operation,'enabled':int(node.attrib[DT+'enabled']),
                        'module_version':node.attrib.get(DT+'modversion'),
                        'params_sha256':hashlib.sha256(node.attrib.get(DT+'params','').encode()).hexdigest()})
    if not {'rawprepare','demosaic','colorin','colorout','temperature','flip'}.issubset({v['operation'] for v in history if v['enabled']}):
        raise ValueError('BLOCKED: required darktable RAW modules missing')
    tree.write(output,encoding='utf-8',xml_declaration=True)
    return history

def verify_rt(path,expected_ev=0):
    p=configparser.ConfigParser(strict=False); p.read(path,encoding='utf-8')
    # Pinned RT 5.13 procparams.cc enum strings. Saving a PP3 is not proof of
    # execution: unknown X-Trans strings fall through to nodemosaic(false).
    if p['RAW X-Trans']['Method'] not in ('4-pass','3-pass (best)','2-pass','1-pass (medium)','fast','mono','none'):
        raise ValueError('BASE_BLOCKED: unsupported RT 5.13 X-Trans method token')
    off=['Sharpening','SharpenEdge','SharpenMicro','PostDemosaicSharpening','PostResizeSharpening',
         'Impulse Denoising','Directional Pyramid Denoising','Vibrance','Color appearance','Film Simulation','HLRecovery']
    for section in off:
        if p[section].getboolean('Enabled'): raise ValueError(f'BASE_BLOCKED RT {section} still enabled')
    if p['Exposure'].getboolean('Auto') or abs(p['Exposure'].getfloat('Compensation')-expected_ev)>1e-6:
        raise ValueError('BASE_BLOCKED RT exposure config ignored')
    if p['White Balance']['Setting']!='Camera': raise ValueError('BASE_BLOCKED RT WB not camera')
    if p['RAW'].getboolean('CA') or p['LensProfile']['LcMode']!='none': raise ValueError('BASE_BLOCKED RT optional CA/lens enabled')
    if p['Crop'].getboolean('Enabled') or p['Resize'].getboolean('Enabled'): raise ValueError('BASE_BLOCKED RT unexpected geometry')
    if p['Color Management']['OutputProfile']!='RTv4_sRGB': raise ValueError('BASE_BLOCKED RT output ICC setting ignored')
    return {'merged_profile':str(path),'active_enabled_sections':[s for s in p.sections() if p[s].get('Enabled')=='true'],
            'white_balance':'Camera; resolved internally by RT (not copied from ours)',
            'demosaic_Bayer':dict(p['RAW Bayer']),'demosaic_XTrans':dict(p['RAW X-Trans']),
            'saved_settings_checked':True,'method_token_supported_by_pinned_source':True,
            'execution_dispatch_observed':False,'base_optional_modules_disabled':off}

def output_cache_valid(record,key):
    if record.get('cache_key')!=key or not output_eligible(record): return False
    actual_exe=binaries()[record['engine_id']]
    if not actual_exe.exists() or sha(actual_exe)!=record['cache_inputs']['engine']: return False
    paths=[record['normalized_export']]+[v.get('archive',v) for v in record['native_export']]
    paths += [{'path':record['settings_path'],'sha256':record['settings_sha256']}]
    paths += [{'path':f"profiles/{record['descriptor']['icc_sha256']}.icc",'sha256':record['descriptor']['icc_sha256']},
              {'path':'profiles/target-sRGB.icc','sha256':record['descriptor']['target_icc_sha256']}]
    return all((RUN/v['path']).is_file() and sha(RUN/v['path'])==v['sha256'] for v in paths)

def render(item,engine,resume=True,repeat=None,perturb=False):
    lock=load(RUN/'engines.lock.json'); engine_lock=lock['engines'][engine]
    original=RUN/item['path']; key_inputs={'source':sha(original),'engine':engine_lock['sha256'],
            'dependencies':engine_lock['dependency_digest'],'policy':sha(BASE/'benchmark.policy.json'),
            'python_dependencies':lock['python']['project_local_dependency_digest'],'lcms':lock['lcms']['sha256'],
            'adapter_normalizer_metrics':digest({p.name:sha(p) for p in sorted((ROOT/'raw_benchmark').glob('*.py')) if p.name not in ('report.py','__main__.py')}),
            'profile':sha(CONFIG/'base.pp3'),'target_profile':sha(RUN/'profiles/target-sRGB.icc'),
            'look':digest({str(p.relative_to(ROOT/'fixtures/looks/identity-technical-fixture')):sha(p) for p in (ROOT/'fixtures/looks/identity-technical-fixture').rglob('*') if p.is_file()}),
            'mode':'BASE_CONTROLLED','perturb':perturb,
            'execution_variant':'CPU1_REFERENCE' if engine=='rawtherapee' else 'CPU4_DEFAULT'}
    key=digest(key_inputs)
    root=RUN/('config-effect' if perturb else 'repeats' if repeat is not None else 'jobs')/item['source_id']/engine
    if repeat is not None: root=root/f'repeat-{repeat}'
    latest=root/'latest.json'
    if resume and not perturb and latest.exists():
        record=load(latest)
        if output_cache_valid(record,key):
            cached=dict(record); cached['execution']=dict(record['execution'],cache_hit=True,wall_seconds=None,
                 original_render_wall_seconds=record['execution']['wall_seconds'])
            return cached
    budget(1_200_000_000)
    folder=root/f'attempt-{time.time_ns()}'; folder.mkdir(parents=True)
    raw=folder/('input'+original.suffix); shutil.copyfile(original,raw)
    record={'job_id':rel(folder),'source_id':item['source_id'],'engine_id':engine,'source_sha256':item['sha256'],
            'mode':'BASE_CONTROLLED','execution_variant':key_inputs['execution_variant'],'cache_key':key,'cache_inputs':key_inputs,
            'engine_lock_sha256':sha(RUN/'engines.lock.json'),'review_status':'NOT_REVIEWED',
            'technical_checks':[],'comparison_eligibility':'NOT_EVALUATED','quality_triage':'NOT_EVALUATED'}
    exe=Path(engine_lock['path']); settings=None
    try:
        if sha(exe)!=engine_lock['sha256']: raise ValueError('BLOCKED: actual executable changed')
        if engine=='ours':
            settings=folder/'recipe.json'; look=ROOT/'fixtures/looks/identity-technical-fixture'
            init=process([exe,'init-recipe',raw,'--look',look,'--amount','0','--out',settings],folder/'init')
            if init['status']!='SUCCESS': raise ValueError('recipe init failed; see init logs')
            recipe=load(settings)
            if perturb: recipe['adjustments']['exposureEV']=1; write(settings,recipe)
            record['effective_settings']={'recipe':recipe,'creative_look':'amount 0; identity asset','sharpen':'not implemented','noise_reduction':'not implemented',
                 'precision':'production FP32 buffer before quantization; JPEG only metadata carrier'}
            args=[exe,'render',raw,'--recipe',settings,'--look',look,'--out',folder/'output.jpg',
                  '--report',folder/'engine-report.json','--diagnostic-pixels',folder/'native']
        elif engine=='rawtherapee':
            settings=folder/'profile.pp3'; shutil.copyfile(CONFIG/'base.pp3',settings)
            if perturb: settings.write_text(settings.read_text().replace('Compensation=0','Compensation=1'))
            args=[exe,'-O',folder/'native.tif','-p',settings,'-tz','-b16','-c',raw]
        else:
            # Obtain version-valid, camera-specific module blobs from THIS executable.
            default=process(dt_argv(raw,folder/'default-native.tif',folder/'default'),folder/'default-process')
            record['default_initialization']=default
            if default['status']!='SUCCESS': raise ValueError('BASE_BLOCKED: headless default history generation failed')
            with tifffile.TiffFile(folder/'default-native.tif') as t:
                generated=t.pages[0].tags.get(700)
                if not generated: raise ValueError('BASE_BLOCKED: no generated XMP processing history')
                (folder/'generated.xmp').write_bytes(generated.value)
            settings=folder/'controlled.xmp'
            record['effective_settings']={'history':dt_control(folder/'generated.xmp',settings,1.25 if perturb else 1),
                 'param_provenance':'generated by actual pinned darktable; disable optional modules; WB perturb validated against temperature.c v4 (20 bytes).',
                 'exposure_ev':0,'white_balance':'actual per-camera default temperature/as-shot; no shared gains',
                 'disabled':'all history modules outside required RAW/WB/input/output/orientation allowlist, including highlight reconstruction'}
            args=dt_argv(raw,folder/'native.tif',folder/'controlled',settings)
        record['settings_path']=rel(settings); record['settings_sha256']=sha(settings)
        # Uniform RT resource policy, after measured X-Trans 4-thread
        # nondeterminism. Same supported algorithm and BASE settings; all CFA.
        execution=process(args,folder/'render',env_extra={'OMP_NUM_THREADS':'1','OMP_THREAD_LIMIT':'1'} if engine=='rawtherapee' else None)
        record['execution']=execution
        if execution['status']!='SUCCESS':
            text=(RUN/execution['stderr_path']).read_text(errors='replace')
            if 'unsupported' in text.lower(): execution['status']='UNSUPPORTED'
            raise RuntimeError(f"{execution['status']}: converter did not complete; logs retained")
        if engine=='rawtherapee': record['effective_settings']=verify_rt(folder/'native.tif.pp3',1 if perturb else 0)
        if engine=='darktable':
            with tifffile.TiffFile(folder/'native.tif') as t:
                effective=t.pages[0].tags.get(700)
                if not effective: raise ValueError('BASE_BLOCKED: export has no effective XMP')
                (folder/'effective.xmp').write_bytes(effective.value)
            controlled_tree=ET.parse(folder/'effective.xmp')
            operations=[{'operation':n.attrib[DT+'operation'],'enabled':int(n.attrib[DT+'enabled'])} for n in controlled_tree.iter() if DT+'operation' in n.attrib]
            if any(v['enabled'] and v['operation'] not in ALLOWED for v in operations): raise ValueError('BASE_BLOCKED: optional module unexpectedly active')
            record['effective_settings']['exported_history']=operations
        normalized,d,native,export=normalize(folder,engine)
        record['descriptor']=d; record['native_export']=native; record['normalized_export']=export
        record['metrics']=measurements(normalized,folder); del normalized
        record['source_unchanged']=sha(original)==item['sha256'] and sha(raw)==item['sha256']
        if not record['source_unchanged']: raise ValueError('source mutation detected')
        record['technical_checks']=[{'name':n,'status':'PASS'} for n in ('actual_precision','finite_native','finite_normalized','ICC_transform','source_unchanged','effective_history_or_PP3','lossless_roundtrip')]
        record['comparison_eligibility']='ELIGIBLE_PENDING_GEOMETRY'
    except Exception as exc:
        status='BLOCKED' if 'BLOCKED' in str(exc) else 'FAILED'
        execution=record.get('execution',{'status':status,'argv':[],'exit_code':None,'wall_seconds':None,'peak_memory_bytes':None,'cache_hit':False})
        # Export execution and downstream reference eligibility are separate.
        # A successful export remains SUCCESS even if its pixels/config fail.
        record['reference_validation_status']=status
        record['reference_eligibility']='BLOCKED' if status=='BLOCKED' else 'INCONCLUSIVE'
        record['execution']=execution; record['reason']=str(exc)
        record['technical_checks'].append({'name':'adapter/output/normalization','status':'BLOCKED' if status=='BLOCKED' else 'FAIL','reason':str(exc)})
        record['comparison_eligibility']='NOT_COMPARABLE'
    finally:
        # Originals remain; remove only the per-job RAW copy after hash evidence is recorded.
        record['working_copy_sha256_after']=sha(raw) if raw.exists() else None
        record['original_sha256_after']=sha(original)
        record['source_unchanged']=record['working_copy_sha256_after']==item['sha256']==record['original_sha256_after']
        raw.unlink(missing_ok=True)
        record['working_copy_policy']='real independent copy; converter sidecars remain in job; copy removed after post-run hash check'
        write(folder/'result.json',record); write(latest,record)
    return record
