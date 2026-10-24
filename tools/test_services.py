"""Run real PostgreSQL storage tests in an owned disposable container. Never print generated credentials."""
import os, pathlib, secrets, subprocess, sys, time, urllib.request, json, tempfile
from test_pki import prepare
root = pathlib.Path(__file__).resolve().parents[1]
password = secrets.token_hex(24)
container = None
dependencies=[]
pki=None
def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)
try:
    container = subprocess.check_output(['docker','run','--rm','-d','-e',f'POSTGRES_PASSWORD={password}',
        '-p','127.0.0.1::5432','postgres:16'], text=True).strip()
    for _ in range(60):
        if subprocess.run(['docker','exec',container,'pg_isready','-U','postgres'],capture_output=True).returncode == 0: break
        time.sleep(0.5)
    else: raise RuntimeError('Test database did not become ready')
    run(['docker','exec','-i',container,'psql','-U','postgres','-v','ON_ERROR_STOP=1'],
        input=f"CREATE ROLE knowledge_test LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS;",text=True,capture_output=True)
    port=subprocess.check_output(['docker','inspect','--format','{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',container],text=True).strip()
    env=dict(os.environ,KNOWLEDGE_TEST_URL=f'jdbc:postgresql://127.0.0.1:{port}/postgres?sslmode=disable',
        KNOWLEDGE_TEST_PASSWORD=password,JAVA_TOOL_OPTIONS='-Duser.timezone=UTC')
    if '--with-tls' in sys.argv:
        pki=tempfile.TemporaryDirectory(prefix='olo-knowledge-pki-')
        env.update(KNOWLEDGE_PKI=prepare(pki.name,password),KNOWLEDGE_PKI_PASSWORD=password)
    if '--with-vectors' in sys.argv:
        def dependency(image, internal_port, extra=()):
            ident=subprocess.check_output(['docker','run','--rm','-d','-p',f'127.0.0.1::{internal_port}',*extra,image],text=True).strip()
            dependencies.append(ident)
            exposed=subprocess.check_output(['docker','inspect','--format',f'{{{{(index (index .NetworkSettings.Ports "{internal_port}/tcp") 0).HostPort}}}}',ident],text=True).strip()
            return f'http://127.0.0.1:{exposed}'
        qdrant=dependency('qdrant/qdrant:latest',6333)
        models=root/'build/ollama-models';models.mkdir(parents=True,exist_ok=True)
        ollama=dependency('ollama/ollama:latest',11434,('-v',f'{models.as_posix()}:/root/.ollama'))
        def exchange(url, data=None, timeout=180):
            request=urllib.request.Request(url,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)
        for _ in range(60):
            try: exchange(ollama+'/api/tags');break
            except (OSError,ValueError):time.sleep(.5)
        print('Preparing pinned real embedding fixture and Qdrant',flush=True)
        exchange(ollama+'/api/pull',{'model':'all-minilm:latest','stream':False})
        tags=exchange(ollama+'/api/tags')['models']
        digest=next(m['digest'] for m in tags if m['name']=='all-minilm:latest')
        exchange(ollama+'/api/embed',{'model':'all-minilm:latest','input':['warmup'],'truncate':False})
        env.update(KNOWLEDGE_QDRANT=qdrant,KNOWLEDGE_OLLAMA=ollama,KNOWLEDGE_MODEL_DIGEST='sha256:'+digest.removeprefix('sha256:'))
    gradle=os.environ.get('GRADLE',str(pathlib.Path.home()/'.gradle/wrapper/dists/gradle-8.12-bin/cetblhg4pflnnks72fxwobvgv/gradle-8.12/bin/gradle.bat'))
    run([gradle,'test','--rerun-tasks','--console=plain'],cwd=root,env=env)
finally:
    for dependency in dependencies:subprocess.run(['docker','stop',dependency],capture_output=True)
    if container: subprocess.run(['docker','stop',container],capture_output=True)
    if pki:pki.cleanup()
