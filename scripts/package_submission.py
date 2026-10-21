"""Create a deterministic allowlisted source/fixture/report archive, never local state."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from report_metadata import portable
DATA_DIRS = {'runtime','development','evaluation','testing','activity_corpus',
             'activity_evaluation','policy_evaluation','workflow_evaluation',
             'live_extraction_evaluation','deterministic_extraction_evaluation','bank_integration_validation'}


def files(root=ROOT):
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink(): continue
        parts = path.relative_to(root).parts
        if any(p.startswith('.') and p not in ('.env.example','.gitignore','.streamlit') for p in parts): continue
        if any(p in ('__pycache__','dist','node_modules') for p in parts): continue
        ok = (len(parts)==1 and (path.suffix in ('.py','.md') or path.name in
               ('requirements.txt','requirements-llm.txt','.env.example','.gitignore','SUBMISSION_VERIFICATION.json')))
        ok |= parts == ('.streamlit','config.toml')
        ok |= parts[0] in ('scripts','tests','evaluation') and path.suffix in ('.py','.json')
        ok |= parts[0]=='policies' and path.suffix=='.json'
        ok |= parts[0]=='data' and path.suffix in ('.json','.md') and (
            (len(parts)>2 and parts[1] in DATA_DIRS) or parts[1] in ('manifest.json','quality_report.json'))
        if ok: yield path


def build(destination):
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    selected = list(files())
    for path in selected:
        if path.suffix=='.json':
            document=json.loads(path.read_text())
            if portable(document)!=document:
                raise ValueError(f'Machine-local path metadata must be removed before packaging: {path.relative_to(ROOT)}')
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in selected}
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            info=zipfile.ZipInfo('transaction-dispute-assistant/'+str(path.relative_to(ROOT)),date_time=(2026,10,21,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=0o100644 << 16
            archive.writestr(info,path.read_bytes())
        info=zipfile.ZipInfo('transaction-dispute-assistant/SUBMISSION_MANIFEST.json',date_time=(2026,10,21,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,json.dumps({'sha256':hashes,'exclusions':'No venv, hidden private state, keys, secrets, caches, database files or symlinks.'},sort_keys=True,indent=2)+'\n')
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(f'{digest}  {destination.name}\n')
    return {'archive':str(destination),'files':len(hashes)+1,'sha256':digest}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/transaction-dispute-assistant.zip')
    print(json.dumps(build(parser.parse_args().output),indent=2))
