#!/usr/bin/env python3
"""Read this project's Actions status and download completed logs/artifacts through the local proxy."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'buhuo666/XIAOMI-PAD-5_nabu-on-IOS'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--proxy', default=os.environ.get('NABU_PROXY', 'http://127.0.0.1:19999'))
    args = parser.parse_args()
    credential = subprocess.run(['git', 'credential', 'fill'], cwd=ROOT,
                                input='protocol=https\nhost=github.com\n\n',
                                text=True, capture_output=True, check=True)
    token = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)['password']
    proxy = urllib.request.ProxyHandler({'http': args.proxy, 'https': args.proxy})
    api_opener = urllib.request.build_opener(proxy, NoRedirect())
    download_opener = urllib.request.build_opener(proxy)
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'User-Agent': 'nabu16-bootstrap'}

    def api(path):
        request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + path, headers=headers)
        with api_opener.open(request, timeout=90) as response:
            return json.load(response)

    def download(path, destination):
        request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + path, headers=headers)
        try:
            response = api_opener.open(request, timeout=90)
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise
            # The signed asset URL carries its own authorization. Do not forward the GitHub credential.
            location = error.headers['Location']
            error.close()
            response = download_opener.open(urllib.request.Request(location, headers={'User-Agent': 'nabu16-bootstrap'}), timeout=90)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with response, destination.open('wb') as stream:
            while data := response.read(1024 * 1024):
                stream.write(data)

    if args.run:
        run = api(f'actions/runs/{args.run}')
    else:
        run = api('actions/runs?branch=nabu16-bootstrap&per_page=1')['workflow_runs'][0]
    run_id, attempt = run['id'], run['run_attempt']
    jobs = api(f'actions/runs/{run_id}/attempts/{attempt}/jobs')['jobs']
    summary = {key: run[key] for key in ['id', 'run_attempt', 'status', 'conclusion', 'head_sha', 'html_url']}
    summary['jobs'] = [{'id': job['id'], 'status': job['status'], 'conclusion': job['conclusion'],
                        'steps': [{'name': step['name'], 'status': step['status'], 'conclusion': step['conclusion']}
                                  for step in job['steps']]} for job in jobs]
    print(json.dumps(summary, ensure_ascii=True), flush=True)
    output = ROOT / 'log/ci/github' / str(run_id) / f'attempt-{attempt}'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'status.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    if args.download and run['status'] == 'completed':
        log_zip = output / 'logs.zip'
        download(f'actions/runs/{run_id}/attempts/{attempt}/logs', log_zip)
        with zipfile.ZipFile(log_zip) as archive:
            archive.extractall(output / 'logs')
        artifacts = api(f'actions/runs/{run_id}/artifacts')['artifacts']
        for artifact in artifacts:
            if artifact['expired']:
                continue
            folder = ROOT / 'artifacts/ci' / f'{run_id}-attempt-{attempt}' / artifact['name']
            package = folder / 'artifact.zip'
            download(f'actions/artifacts/{artifact["id"]}/zip', package)
            with zipfile.ZipFile(package) as archive:
                archive.extractall(folder)
            print('Artifact saved:', folder, flush=True)
        (output / 'artifacts.json').write_text(json.dumps(artifacts, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
