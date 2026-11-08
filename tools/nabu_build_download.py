"""Retry the HTTP 504 responses observed while acquiring CI build inputs."""
import time
import urllib.error


def open_build_input(open_url, request, timeout):
    for attempt in range(3):
        try:
            return open_url(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code != 504 or attempt == 2:
                raise
            error.close()
            print(f'Build input HTTP 504; retry {attempt + 1}/2', flush=True)
            time.sleep(2 * (attempt + 1))
