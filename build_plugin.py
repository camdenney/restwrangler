"""Build the installable plugin ZIP using only the Python standard library."""
from pathlib import Path
import ast
import configparser
import zipfile

ROOT = Path(__file__).resolve().parent
PLUGIN = ROOT / 'public_agency_services'
FILES = ('__init__.py', 'public_services.py', 'metadata.txt', 'icon.png',
         'README.md', 'LICENSE', 'test_helpers.py', 'test_discovery.py')


def main():
    config = configparser.ConfigParser()
    config.read(PLUGIN / 'metadata.txt', encoding='utf-8')
    for name in FILES:
        path = PLUGIN / name
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'), filename=name)
    output = ROOT / 'downloads' / 'RestWrangler_QGIS.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(PLUGIN / name, f'public_agency_services/{name}')
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('ZIP integrity check failed')
    print(f"Built {config['general']['name']} {config['general']['version']}: {output}")


if __name__ == '__main__':
    main()
