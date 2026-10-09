"""Build the self-contained macOS arm64 app from local, verified resources."""
import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'build/releases/survey-report/Paneloom.app'
PREFIX=Path(sys.base_prefix)

def command(*args):subprocess.run([str(arg) for arg in args],check=True)

def copytree(source,destination,ignore=None):
    shutil.copytree(source,destination,symlinks=True,ignore=ignore,dirs_exist_ok=True)

def copy_assets(source,destination):
    info=json.loads((source/'model.json').read_text())
    filename=info['file']
    if not isinstance(filename,str) or Path(filename).name!=filename:
        raise ValueError('Invalid pinned model filename.')
    model=source/'models'/filename
    if not model.is_file():raise ValueError('Prepare the pinned current model first.')
    copytree(source,destination,shutil.ignore_patterns('models'))
    models=destination/'models';models.mkdir(exist_ok=True)
    command('cp','-c',model,models/filename)

def write_archive(app,archive):
    # ditto produced invalid headers for the >4 GiB model; use standard ZIP64.
    app=Path(app)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as output:
        for path in [app,*sorted(app.rglob('*'))]:
            name=str(path.relative_to(app.parent))
            if path.is_symlink():
                metadata=path.lstat()
                info=zipfile.ZipInfo(name,time.localtime(metadata.st_mtime)[:6])
                info.create_system=3;info.external_attr=metadata.st_mode<<16
                output.writestr(info,os.readlink(path).encode('utf-8'))
            else:
                output.write(path,name,compress_type=zipfile.ZIP_DEFLATED,compresslevel=1)

def main():
    global APP
    parser=argparse.ArgumentParser();parser.add_argument('--zip',action='store_true');parser.add_argument('--output',type=Path,default=APP);parser.add_argument('--archive',type=Path,default=ROOT/'dist/Paneloom-0.8.1-macOS-arm64.zip');args=parser.parse_args()
    APP=args.output.resolve()
    if not APP.is_relative_to(ROOT/'build') or APP.suffix!='.app':raise SystemExit('Build output must be an .app directory under build/.')
    if sys.platform!='darwin':raise SystemExit('This build targets macOS.')
    info=json.loads((ROOT/'assets/model.json').read_text())
    if not (ROOT/'assets/models'/info['file']).is_file():raise SystemExit('Prepare the pinned current model first.')
    (ROOT/'build/module-cache').mkdir(parents=True,exist_ok=True)
    command('xcrun','swift','-module-cache-path',ROOT/'build/module-cache',ROOT/'tools/generate_app_icon.swift')
    if APP.exists():shutil.rmtree(APP)
    macos=APP/'Contents/MacOS';resources=APP/'Contents/Resources'
    macos.mkdir(parents=True);resources.mkdir(parents=True)
    shutil.copy2(ROOT/'macos/Info.plist',APP/'Contents/Info.plist')
    (APP/'Contents/PkgInfo').write_bytes(b'APPL????')
    copytree(ROOT/'src',resources/'src',shutil.ignore_patterns('__pycache__','*.pyc'))
    copytree(ROOT/'web',resources/'web')
    copy_assets(ROOT/'assets',resources/'assets')
    if (ROOT/'macos/AppIcon.icns').exists():shutil.copy2(ROOT/'macos/AppIcon.icns',resources/'AppIcon.icns')
    framework=APP/'Contents/Frameworks/Python.framework'
    version=framework/'Versions/3.12';version.mkdir(parents=True)
    shutil.copy2(PREFIX/'Python',version/'Python')
    copytree(PREFIX/'lib',version/'lib',shutil.ignore_patterns('site-packages','__pycache__','*.pyc','test','tests','idlelib','tkinter','turtledemo','ensurepip','_tkinter*','*.a','pkgconfig','sqlite3.47.2','itcl4.3.2','tcl8','tcl8.6','tk8.6','tclConfig.sh','tkConfig.sh','tclooConfig.sh','tdbc1.1.10','tdbcmysql1.1.10','tdbcodbc1.1.10','tdbcpostgres1.1.10','thread2.8.11'))
    copytree(PREFIX/'Resources',version/'Resources',shutil.ignore_patterns('__pycache__'))
    (framework/'Versions/Current').symlink_to('3.12')
    (framework/'Python').symlink_to('Versions/Current/Python')
    (framework/'Resources').symlink_to('Versions/Current/Resources')
    shutil.copy2(Path(sys.executable).resolve(),macos/'PythonRunner')
    binaries=[macos/'PythonRunner',version/'Python',*version.rglob('*.so'),*version.rglob('*.dylib'),version/'Resources/Python.app/Contents/MacOS/Python']
    original=str(PREFIX)+'/'
    for binary in binaries:
        if not binary.exists() or binary.is_symlink():continue
        result=subprocess.run(['otool','-L',str(binary)],capture_output=True,text=True,check=True)
        dependencies={line.strip().split(' (',1)[0] for line in result.stdout.splitlines() if line.strip().startswith(original)}
        for dependency in dependencies:
            target=version/dependency[len(original):]
            relative=os.path.relpath(target,binary.parent)
            command('install_name_tool','-change',dependency,'@loader_path/'+relative,binary)
        if binary==version/'Python':command('install_name_tool','-id','@rpath/Python.framework/Versions/3.12/Python',binary)
    (ROOT/'build/module-cache').mkdir(exist_ok=True)
    command('xcrun','swiftc',ROOT/'macos/App.swift','-o',macos/'PersonaLab','-framework','AppKit','-framework','WebKit','-target','arm64-apple-macos14.0','-module-cache-path',ROOT/'build/module-cache')
    for binary in binaries:
        if binary.exists() and not binary.is_symlink():command('codesign','--force','--sign','-',binary)
    command('codesign','--force','--deep','--sign','-',APP)
    command('codesign','--verify','--deep','--strict',APP)
    env={**os.environ,'PYTHONHOME':str(version),'PYTHONPATH':str(resources/'src'),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}
    env.pop('__PYVENV_LAUNCHER__',None)
    command_env=subprocess.run([str(macos/'PythonRunner'),'-s','-c','import sys,ssl,sqlite3,threading,persona_desktop.server; print(sys.prefix); print(ssl.__file__); print(persona_desktop.server.__file__)'],env=env,capture_output=True,text=True,check=True)
    assert str(APP) in command_env.stdout,command_env.stdout
    print(command_env.stdout,flush=True)
    print(APP,flush=True)
    if args.zip:
        archive=args.archive.resolve()
        if not archive.is_relative_to(ROOT/'dist') or archive.suffix!='.zip':raise SystemExit('Archive output must be a .zip file under dist/.')
        archive.parent.mkdir(exist_ok=True)
        partial=archive.with_suffix('.zip.part');partial.unlink(missing_ok=True)
        write_archive(APP,partial)
        partial.replace(archive)
        print(archive,flush=True)

if __name__=='__main__':main()
