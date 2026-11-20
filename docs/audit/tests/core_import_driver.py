import subprocess, os, sys, concurrent.futures as cf
ROOT = sys.argv[1]
PY = sys.argv[2]
mods = []
for dp, dn, fn in os.walk(ROOT):
    for f in fn:
        if f.endswith('.py'):
            rel = os.path.relpath(os.path.join(dp, f), ROOT)
            if rel == '__init__.py':
                continue
            m = rel[:-3].replace(os.sep, '.')
            if m.endswith('.__init__'):
                m = m[:-9]
            mods.append(m)
mods.sort()
env = dict(os.environ, PG_HOST='127.0.0.1', PG_PASSWORD='x', API_KEY='x', MANAGEMENT_API_KEY='x', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=ROOT)
def run(m):
    code = f"import importlib; importlib.import_module({m!r}); print('OK')"
    try:
        p = subprocess.run([PY, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
        if p.returncode == 0:
            return (m, 'OK', '')
        lines = [l for l in p.stderr.strip().splitlines() if l.strip()]
        return (m, 'FAIL', lines[-1] if lines else f'rc={p.returncode}')
    except subprocess.TimeoutExpired:
        return (m, 'TIMEOUT', 'no result within 10s')
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(run, mods))
ok = sum(1 for r in res if r[1]=='OK')
print(f'total={len(res)} ok={ok} fail={len(res)-ok}')
for m, s, e in res:
    if s != 'OK':
        print(f'{s} {m}: {e}')
