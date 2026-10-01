"""Final WB contract and source mutation checks. Does not alter original RAWs."""
import argparse,json,subprocess,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'benchmark/python-deps')]
from tools.next_step.core import OLD,CLI,HARNESS,LOOK,load,write,sha,common,session as run_session
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);common.RUN=out
    empty={'execution':{'status':'SUCCESS'}}
    assert not common.output_eligible(empty)
    valid=dict(empty,descriptor={'width':1},normalized_export={'path':'example'})
    assert common.output_eligible(valid)
    for status in ['BLOCKED','INCONCLUSIVE']:assert not common.output_eligible(dict(valid,reference_eligibility=status))
    write(out/'eligibility-contract.json',{'status':'VERIFIED','successful_export_without_valid_reference_is_not_eligible':True,'export_status_preserved':empty['execution']['status']})
    items={i['source_id']:i for i in load(OLD/'corpus.manifest.json')['items']}
    old=load(OLD/'jobs/R001/ours/latest.json');recipe=load(OLD/old['settings_path']);rpath=out/'recipe.json';write(rpath,recipe)
    folder=out/'wb';folder.mkdir();source=OLD/items['R011']['path']
    proc=subprocess.run([str(HARNESS),'decode-only',str(source),str(LOOK),str(rpath),str(folder)],capture_output=True,text=True,timeout=60)
    (folder/'decode-stdout.json').write_text(proc.stdout);(folder/'decode-stderr.log').write_text(proc.stderr)
    assert proc.returncode==0
    init=common.process([CLI,'init-recipe',source,'--look',LOOK,'--out',folder/'no-recipe.json'],folder/'init')
    err=json.loads((folder/'init/stderr.log').read_text());assert err['errorCode']=='AS_SHOT_WB_UNAVAILABLE' and not (folder/'no-recipe.json').exists()
    failures=[]
    for name,gains in [('missing',None),('zero',[0,0,0,0])]:
        bad=json.loads(json.dumps(recipe));bad['source']['sha256']=items['R011']['sha256'];bad['adjustments']['whiteBalance']['resolvedCameraMultipliers']=gains
        path=folder/f'{name}.json';write(path,bad)
        result=common.process([CLI,'render',source,'--look',LOOK,'--recipe',path,'--out',folder/f'{name}.jpg','--report',folder/f'{name}-report.json'],folder/name)
        assert result['status']=='FAILED' and not (folder/f'{name}.jpg').exists()
        assert 'PE_RECIPE_INVALID' in (folder/name/'stderr.log').read_text()
        failures.append({'case':name,'execution':result})
    write(folder/'contract.json',{'status':'VERIFIED','decode':json.loads(proc.stdout),'asShot_error':err,'invalid_replay':failures,'policy':'Proposed; no custom or auto WB acceptance for R011. No legacy recipe changed.'})
    # Mutation is only on an independent temporary RAW copy. Original is hashed
    # before/after; the test restores its own byte and confirms normal replay.
    source=OLD/items['R001']['path'];copy=out/'mutation-source.nef';shutil.copyfile(source,copy);session=out/'source-mutation';session.mkdir()
    log=(session/'stderr.log').open('w');process=subprocess.Popen([str(HARNESS),'session',str(copy),str(LOOK),str(rpath),str(session)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True)
    def send(c):process.stdin.write(json.dumps(c)+'\n');process.stdin.flush();return json.loads(process.stdout.readline())
    first=send({'name':'before','generation':1})
    with copy.open('r+b') as f:byte=f.read(1);f.seek(0);f.write(bytes([byte[0]^1]))
    changed=send({'name':'changed','generation':2})
    with copy.open('r+b') as f:f.write(byte)
    restored=send({'name':'restored','generation':3})
    process.stdin.close();process.wait(timeout=60);log.close()
    assert first['status']==0 and changed['status']==6 and changed['imageIsNull'] and restored['status']==0
    assert restored['cacheHit'] and first['pixelSha256']==restored['pixelSha256']
    assert sha(source)==sha(copy)==items['R001']['sha256']
    write(out/'source-invalidation.json',{'status':'VERIFIED','original_unchanged':True,'before':first,'changed':changed,'restored':restored})
    rotated=load(OLD/'jobs/R007/ours/latest.json');rpath=out/'rotated-recipe.json';shutil.copyfile(OLD/rotated['settings_path'],rpath)
    rows=run_session('session',OLD/items['R007']['path'],LOOK,rpath,out/'orientation-preview',[
        {'name':'initial','generation':1,'verifyUncached':True},
        {'name':'geometry','generation':2,'rotation':1,'mirror':True,'verifyUncached':True},
        {'name':'restore','generation':3}])
    assert rows[0]['uncachedMaxAbs']==rows[1]['uncachedMaxAbs']==0
    assert rows[0]['pixelSha256']==rows[2]['pixelSha256'] and rows[2]['cacheHit']
    assert rows[0]['height']>rows[0]['width'] and rows[1]['width']>rows[1]['height']
    write(out/'orientation-regression.json',{'status':'VERIFIED','source':'R007','sourceFlip':5,'rows':rows})
if __name__=='__main__':main()
