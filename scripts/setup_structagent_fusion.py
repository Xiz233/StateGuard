"""Materialize the pinned StructAgent source plus the reviewed fusion overlay."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_URL = 'https://github.com/WenyiWU0111/StructAgent.git'
UPSTREAM_COMMIT = 'bd9452afab6c9c472af8d9a1fff2d7f4c33d499e'
OVERLAY = ROOT / 'integrations/structagent/overlay'


def copy_tree(source, destination):
    copied = {}
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if '__pycache__' in relative.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError(f'Symlinks are not publication inputs: {relative}')
        if path.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.expanduser().resolve()
    if destination.exists():
        parser.error('Destination already exists; choose a new directory to preserve existing work.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'clone', '--no-checkout', UPSTREAM_URL, str(destination)], check=True)
    subprocess.run(['git', '-C', str(destination), 'checkout', '--detach', UPSTREAM_COMMIT], check=True)
    hashes = copy_tree(OVERLAY, destination)
    vendor = destination / 'vendor/stateguard'
    if vendor.exists():
        raise RuntimeError('Pinned upstream unexpectedly contains vendor/stateguard')
    state_hashes = copy_tree(ROOT / 'stateguard', vendor)
    manifest = {'upstream_url': UPSTREAM_URL, 'upstream_commit': UPSTREAM_COMMIT,
                'overlay_sha256': hashes, 'stateguard_sha256': state_hashes}
    (destination / 'FUSION_SOURCE.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Fusion source prepared in {destination}. No model or experiment has been started.')


if __name__ == '__main__':
    main()
