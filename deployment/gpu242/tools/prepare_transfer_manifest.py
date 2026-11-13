"""Resolve package-local system paths after moving the kit to another PC."""
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT/'system/transfer-files.template.json').read_text(encoding='utf-8'))
for item in data['files']:
    source = ROOT/'system'/item['filename']
    if source.stat().st_size != item['bytes']:
        raise RuntimeError('Missing or incomplete system file: ' + item['filename'])
    item['source'] = str(source.resolve())
out = ROOT/'system/transfer-files.json'
out.write_text(json.dumps(data, indent=2), encoding='utf-8')
print(out)
