"""Offline regression for checkpoint forwarding and preservation of target ADT data."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import prepare_chain
from inspect_early_boot import inspect_adt, inspect_handoff
from make_nabu_adt import make_tree, parse


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix='nabu224-early-') as directory:
        root = Path(directory)
        (root/'target-inputs/personalized').mkdir(parents=True)
        (root/'device/target').mkdir(parents=True)
        identity = json.dumps({'device_serial_sha256': 'fixture-only'})
        (root/'target-inputs/personalized/receipt.json').write_text(identity)
        (root/'device/target/inventory.json').write_text(identity)
        for checkpoint in (0, 1, 5, 12, 17, 19, 21):
            argv = ['prepare_chain.py', '--gpt-backup', 'fixture-gpt',
                    '--log-preparation', 'fixture-preparation.json', '--output', 'fixture-chain',
                    '--checkpoint', str(checkpoint), '--config', 'fixture-menu.toml']
            with patch.object(prepare_chain, 'ROOT', root), patch.object(sys, 'argv', argv), \
                    patch.object(prepare_chain.subprocess, 'run') as run:
                prepare_chain.main()
                command = run.call_args.args[0]
                assert command[command.index('--checkpoint')+1] == str(checkpoint)
                assert command[command.index('--config')+1] == 'fixture-menu.toml'
                assert '--apply' not in command
            # Same synthetic target seed, nonce and firmware in both trees.
            options = dict(bootstrap=True, wifi_mac=bytes.fromhex('020000000224'),
                           image4_nonce_key=bytes(range(16)),
                           modem_firmware={'fixture-firmware': bytes(range(256))*1024})
            before = make_tree(bytes(range(64)), 0, **options)
            after = make_tree(bytes(range(64)), checkpoint, **options)
            info = inspect_adt(after.encode())
            assert info['nabu_handoff_inputs_valid']
            assert info['chosen']['nabu-kernel-checkpoint'] == checkpoint
            old_tree = parse(before.encode())
            new_tree = parse(after.encode())
            new_tree[1][0][0]['nabu-kernel-checkpoint'] = old_tree[1][0][0]['nabu-kernel-checkpoint']
            assert new_tree == old_tree
            checks.append(f'checkpoint {checkpoint}: wrapper forwards selection; all other ADT bytes preserved')
        with patch.object(sys, 'argv', ['prepare_chain.py', '--gpt-backup', 'g',
                '--log-preparation', 'l', '--output', 'o', '--checkpoint', '99']), \
                patch.object(prepare_chain.subprocess, 'run') as run, \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                prepare_chain.main()
            except SystemExit as error:
                assert error.code == 2 and not run.called
            else:
                raise AssertionError('Unsupported checkpoint accepted')
        checks.append('unsupported checkpoint rejected before any subprocess')
    observed = inspect_handoff('kernel_va=fffffff007004000 allocated_pa=c4804000 '
        'allocated_bytes=40000000 args_pa=e4c46000 entry_pa=c4c46000\n'
        'kernel_checkpoint=5 callback_pa=e6000000\nargs=private-text-omitted')
    assert observed['allocated_bytes'] == '0x40000000' and observed['kernel_checkpoint'] == 5
    assert 'private-text-omitted' not in json.dumps(observed)
    checks.append('handoff hexadecimal fields parsed; full command line omitted')
    report = {'status': 'offline-checks-passed', 'checks': checks, 'count': len(checks),
              'device_operations_performed': False, 'second_tablet_tested': False}
    destination = Path(__file__).resolve().parents[1]/'early-boot-check.json'
    destination.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
