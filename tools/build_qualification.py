"""Build owner-labelled current-source fixture images, so qualification.ps1 stop can remove them."""
import pathlib,subprocess,json

ROOT=pathlib.Path(__file__).resolve().parents[1]
TOOLGATE=ROOT.parent/'olo-toolgate'
CONTROL='olo-toolgate-control:olo-qualification'
QUICKSTART='olo-toolgate-quickstart:olo-m8'
OWNER='io.olo.qualification.owner=olo-knowledge'

def build():
    for image in [CONTROL,QUICKSTART]:
        result=subprocess.run(['docker','image','inspect',image],capture_output=True,text=True)
        if result.returncode==0:
            labels=json.loads(result.stdout)[0]['Config'].get('Labels') or {}
            if labels.get('io.olo.qualification.owner')!='olo-knowledge':
                raise ValueError('Refusing to overwrite an unowned qualification image: '+image)
    version=(TOOLGATE/'VERSION').read_text(encoding='utf-8').strip()
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=TOOLGATE,text=True).strip()
    common=['--label',OWNER,'--build-arg','VERSION='+version,'--build-arg','REVISION='+revision]
    ui=['--build-arg','ADMIN_UI_SOURCE=console-prebuilt'] if (TOOLGATE/'apps/admin-ui/dist/index.html').exists() else []
    subprocess.run(['docker','build','-f','apps/control-plane/Dockerfile',*common,*ui,'--build-arg','QUARKUS_PROFILE=quickstart','-t',CONTROL,'.'],cwd=TOOLGATE,check=True)
    subprocess.run(['docker','build','-f','apps/quickstart/Dockerfile',*common,'--build-arg','CONTROL_IMAGE='+CONTROL,'-t',QUICKSTART,'.'],cwd=TOOLGATE,check=True)

if __name__=='__main__':build()
