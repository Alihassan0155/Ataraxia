"""Activate only after explicit approval of live delivery AND sign-in startup."""
import argparse
import json
from pathlib import Path
import subprocess


ROOT=Path(__file__).resolve().parents[2]


def activate(approved=False):
    python=ROOT/'backend/.venv-import/Scripts/pythonw.exe'
    script=ROOT/'backend/watch_batch_sync.py'
    target=ROOT/'backend/reports/automatic_batch_sync_20261018'
    command=subprocess.list2cmdline([str(python),'-B',str(script)])
    plan={'status':'disabled_pending_explicit_activation_approval',
          'scope':1140,'batch_size':10,'max_wait_seconds':1800,
          'startup':'HKCU Run / AtaraxiaBatchSync','starts_at':'current user sign-in',
          'command':command,'production_writes':0}
    if not approved:return plan
    if not python.exists() or not script.exists():raise ValueError('Watcher entrypoint unavailable')
    if (target/'activation.json').exists():raise FileExistsError('Activation already recorded; inspect before restarting')
    proof=json.loads((target/'writer_integration_report.json').read_text(encoding='utf-8'))
    if not all(proof.get(k) for k in ['transaction_failure_preserves_all_rows',
                                    'older_version_replay_skipped','original_metadata_unchanged']):
        raise ValueError('Writer integration verification missing')
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',
                           0,winreg.KEY_QUERY_VALUE|winreg.KEY_SET_VALUE) as key:
        try:previous=winreg.QueryValueEx(key,'AtaraxiaBatchSync')[0]
        except FileNotFoundError:previous=None
        winreg.SetValueEx(key,'AtaraxiaBatchSync',0,winreg.REG_SZ,command)
    child=subprocess.Popen([str(python),'-B',str(script)],cwd=str(ROOT),
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
    outcome={**plan,'status':'activated','pid':child.pid,'previous_startup_value':previous}
    (target/'activation.json').write_text(json.dumps(outcome,indent=2),encoding='utf-8')
    return {k:v for k,v in outcome.items() if k!='previous_startup_value'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-live-sync-and-startup',action='store_true')
    args=parser.parse_args()
    print(json.dumps(activate(args.approved_live_sync_and_startup),indent=2))
