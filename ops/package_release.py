"""Package an explicit source allowlist, excluding credentials and developer/runtime data."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'artifacts' / 'campus-ai-release.zip'
    output.parent.mkdir(exist_ok=True)
    fixed = ['README.md','.env.example','.gitignore','.dockerignore']
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in fixed:
            archive.write(ROOT/name, name)
        for folder in ['portal','installer','ops','deploy','docs','frontend/src','frontend/public','frontend/scripts']:
            for path in (ROOT/folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.log'):
                    archive.write(path,path.relative_to(ROOT).as_posix())
        for name in ['package.json','package-lock.json','tsconfig.json','vite.config.ts','index.html']:
            archive.write(ROOT/'frontend'/name,'frontend/'+name)
    print('Created artifacts/campus-ai-release.zip; no .env, databases, tools, or installation tickets included.')


if __name__ == '__main__':
    main()
