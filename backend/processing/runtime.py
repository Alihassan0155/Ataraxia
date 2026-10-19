"""Recover exact frozen source bytes into an isolated embedding runtime."""
import hashlib,json,shutil,subprocess
from pathlib import Path

def historical_runtime(annotation):
    annotation=Path(annotation)
    source_run=annotation/'semantic_pipeline/runs/semantic_full_v12'
    frozen=json.loads((source_run/'frozen.json').read_text())
    runtime=annotation.parent/'backend/reports/processing_launcher'/('runtime_'+frozen['fingerprint'][:16])
    runtime.mkdir(parents=True,exist_ok=True)
    def sha(data):return hashlib.sha256(data).hexdigest()
    provenance=runtime/'runtime_provenance.json'
    if provenance.exists():
        saved=json.loads(provenance.read_text())
        if saved['frozen_fingerprint']!=frozen['fingerprint']:raise ValueError('Runtime identity changed')
        for rel,expected in saved['code_hashes'].items():
            if sha((runtime/rel).read_bytes())!=expected:raise ValueError('Recovered runtime changed: '+rel)
        # Never rewrite source files that another embedding process may be using.
        return runtime
    def save(path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists() or path.read_bytes()!=data:path.write_bytes(data)
    # Non-frozen support imports use existing code; frozen files below are exact.
    shutil.copytree(annotation/'src',runtime/'src',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    save(runtime/'pyproject.toml',(annotation/'pyproject.toml').read_bytes())
    (runtime/'configs').mkdir(exist_ok=True)
    recovered={}
    for rel,expected in frozen['definition_hashes'].items():
        if not rel.endswith('.py') and rel not in ('semantic_pipeline/scripts/semantic.py','semantic_pipeline/requirements.txt'):continue
        current=annotation/rel;data=current.read_bytes()
        if sha(data)!=expected:
            candidate=subprocess.run(['git','show','03523a3:annotation/'+rel],cwd=annotation.parent,capture_output=True)
            if candidate.returncode or sha(candidate.stdout)!=expected:raise RuntimeError('Exact historical source unavailable: '+rel)
            data=candidate.stdout
        save(runtime/rel,data);recovered[rel]=sha(data)
    semantic=runtime/'src/ataraxia/semantic'
    for extra in semantic.glob('*.py'):
        if extra.relative_to(runtime).as_posix() not in frozen['definition_hashes']:
            # Only files inside this newly generated runtime, never source files.
            extra.unlink()
    config=frozen['config']
    for key in ('taxonomy','prompt','template','schema','record_schema','metadata_csv'):
        data=(source_run/'definitions'/key).read_bytes()
        if sha(data)!=frozen['definition_hashes'][key]:raise RuntimeError('Frozen definition corruption: '+key)
        relative=Path(config[key])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe frozen definition path')
        save(runtime/relative,data)
    save(runtime/'semantic_pipeline/configs/pipeline_v12.json',(annotation/'semantic_pipeline/configs/pipeline_v12.json').read_bytes())
    # Predictions are a local read snapshot. Context/transcript/cache paths are
    # junctions to existing data; no video copies or model downloads occur.
    for name in config['gemini_sources']:
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe source path')
        save(runtime/relative,(annotation/relative).read_bytes())
    for name in (config['context_dir'],config['transcript_dir'],'.cache'):
        target=annotation/name;link=runtime/name
        link.parent.mkdir(parents=True,exist_ok=True)
        if link.exists():
            if link.resolve()!=target.resolve():raise ValueError('Unexpected runtime data junction')
        else:
            command=['powershell.exe','-NoProfile','-Command',"New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+str(target.resolve()).replace("'","''")+"' | Out-Null"]
            if subprocess.run(command,capture_output=True).returncode:raise RuntimeError('Cannot link existing runtime data')
    manifest={'frozen_fingerprint':frozen['fingerprint'],'source_run':str(source_run),'runtime':str(runtime),'code_hashes':recovered,'historical_commit':'03523a3','purpose':'embedding-only; unchanged frozen history'}
    save(runtime/'runtime_provenance.json',json.dumps(manifest,indent=2).encode())
    return runtime
