#!/usr/bin/env python3
"""Build sandbox-check first; accepts its path. Uses no private documents."""
import ctypes
import errno
import json
import platform
import resource
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='davros-landlock-') as tmp:
    root = Path(tmp)
    (root / 'input').write_text('input')
    (root / 'secret').write_text('secret')
    (root / 'fonts').mkdir()
    (root / 'fonts/font').write_text('font')
    (root / 'fonts.conf').write_text('config')
    (root / 'scratch').mkdir()
    (root / 'scratch/escape').symlink_to(root / 'secret')
    env = dict(FONTCONFIG_FILE=str(root / 'fonts.conf'), DAVROS_PREVIEW_FONTS=str(root / 'fonts'))
    with socket.socket() as tcp, socket.socket(socket.AF_UNIX) as abstract, socket.socket(socket.AF_UNIX) as pathname:
        tcp.bind(('127.0.0.1', 0)); tcp.listen()
        abstract_name = 'davros-landlock-' + str(os.getpid())
        abstract.bind('\0' + abstract_name); abstract.listen()
        pathname.bind(str(root / 'listener.sock')); pathname.listen()
        with (root / 'secret').open() as secret:
            os.dup2(secret.fileno(), 198, inheritable=True)
            args = [binary, str(root / 'input'), str(root / 'scratch/preview.pdf'),
                    '127.0.0.1:' + str(tcp.getsockname()[1]), abstract_name]
            try:
                subprocess.run(args, env=env, pass_fds=(198,), check=True)
            finally:
                os.close(198)
    assert (root / 'secret').read_text() == 'secret'
    assert (root / 'input').read_text() == 'input'
    (root / 'scratch/preview.pdf').unlink(missing_ok=True)

    # Simulate missing/blocked syscalls, including a working ABI query followed
    # by denied ruleset creation, rule addition, or enforcement. The kernel's
    # version alone must never be reported as active protection.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise SystemExit('Availability fault-injection tests require x86_64 or aarch64')
    # The Landlock/close_range numbers are shared by these two Linux ABIs.
    prctl_nr = 157 if platform.machine() == 'x86_64' else 167
    prlimit_nr = 302 if platform.machine() == 'x86_64' else 261
    def filter_setup(syscall, error=errno.EPERM, arg=None, equals=None, lower_limits=False, no_proc=False):
        def setup():
            if no_proc:
                filter_setup(217 if platform.machine() == "x86_64" else 61)()
            if lower_limits:
                resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
                resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
            # Load syscall number; optionally match a 32-bit syscall argument.
            instructions = [Filter(0x20, 0, 0, 0)]
            if arg is None:
                instructions += [Filter(0x15, 0, 1, syscall), Filter(0x06, 0, 0, 0x50000 | error)]
            else:
                instructions += [Filter(0x15, 0, 3, syscall), Filter(0x20, 0, 0, 16 + 8 * arg),
                                 Filter(0x15, 0, 1, equals), Filter(0x06, 0, 0, 0x50000 | error)]
            instructions += [Filter(0x06, 0, 0, 0x7fff0000)]
            filters = (Filter * len(instructions))(*instructions)
            program = Program(len(filters), filters)
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
                raise OSError(ctypes.get_errno(), 'test seccomp setup failed')
        return setup

    cases = [
        ('missing_landlock', 444, errno.ENOSYS, None, None, 'filesystem_isolation', False),
        ('disabled_landlock', 444, errno.EOPNOTSUPP, None, None, 'filesystem_isolation', False),
        ('denied_landlock', 444, errno.EPERM, None, None, 'filesystem_isolation', False),
        ('denied_create', 444, errno.EPERM, 2, 0, 'filesystem_isolation', False),
        ('denied_network', 444, errno.EPERM, 1, 16, 'tcp_isolation', False),
        ('denied_scoping', 444, errno.EPERM, 1, 24, 'signal_isolation', False),
        ('denied_add_rule', 445, errno.EPERM, None, None, 'filesystem_isolation', False),
        ('denied_enforce', 446, errno.EPERM, None, None, 'filesystem_isolation', False),
        ('missing_close_range', 436, errno.ENOSYS, None, None, 'inherited_fds_closed', True),
        ('denied_close_range', 436, errno.EPERM, None, None, 'inherited_fds_closed', True),
        ('dumpability_denied', prctl_nr, errno.EPERM, 0, 4, 'process_dumping_disabled', False),
        ('inherited_no_new_privs', prctl_nr, errno.EPERM, 0, 38, 'no_new_privileges', True),
        ('denied_limits', prlimit_nr, errno.EPERM, None, None, 'address_space_limit', False),
    ]
    baseline = subprocess.run(args + ['probe'], env=env, capture_output=True, text=True, check=True, timeout=30)
    baseline_features = json.loads(baseline.stdout)['features']
    for label, syscall, error, arg, equals, feature, expected in cases:
        with (root / 'secret').open() as secret:
            os.dup2(secret.fileno(), 198, inheritable=True)
            try:
                result = subprocess.run(args + ['probe'], env=env, pass_fds=(198,),
                    preexec_fn=filter_setup(syscall, error, arg, equals), capture_output=True, text=True, timeout=30)
            finally:
                os.close(198)
        assert result.returncode == 0, (label, result.stderr)
        report = json.loads(result.stdout)
        assert report['features'][feature]['enabled'] == expected, (label, report)
        if not expected:
            assert feature in result.stderr, (label, result.stderr)
        if label in ('denied_network', 'denied_scoping'):
            assert report['features']['filesystem_isolation']['enabled'] == baseline_features['filesystem_isolation']['enabled']
        if 'close_range' in label:
            assert '/proc/self/fd fallback' in report['features'][feature]['detail']
        assert not (root / 'scratch/preview.pdf').exists(), label
        print('PASS: availability:', label)

    # Simulate unavailable /proc enumeration as well as close_range.
    with (root / 'secret').open() as secret:
        os.dup2(secret.fileno(), 198, inheritable=True)
        try:
            result = subprocess.run(args + ['probe'], env=env, pass_fds=(198,),
                preexec_fn=filter_setup(436, errno.ENOSYS, no_proc=True), capture_output=True, text=True, timeout=30)
        finally:
            os.close(198)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert not report['features']['inherited_fds_closed']['enabled']
    assert 'exhaustive cleanup unverified' in report['features']['inherited_fds_closed']['detail']
    print('PASS: bounded FD cleanup when close_range and /proc enumeration are unavailable')

    # A lower inherited limit must be preserved, not raised or rejected.
    result = subprocess.run(args + ['probe'], env=env,
        preexec_fn=filter_setup(444, errno.ENOSYS, lower_limits=True), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['features']['address_space_limit']['enabled']
    assert '2147483648' in report['features']['address_space_limit']['detail']
    assert '67108864' in report['features']['output_file_size_limit']['detail']
    print('PASS: tighter inherited resource limits preserved')

    # Exercise the actual CLI preflight and conversion under denied Landlock.
    if len(sys.argv) > 2:
        converter = Path(sys.argv[2]).resolve()
        bundle = converter.parent
        runtime_env = dict(os.environ, DAVROS_PREVIEW_FONTS=str(bundle / 'fonts'),
                           FONTCONFIG_FILE=str(bundle / 'fonts.conf'), RAYON_NUM_THREADS='2')
        source = Path(__file__).resolve().parent / 'tests/fixtures/basic.docx'
        output = root / 'scratch/preview.pdf'
        result = subprocess.run([converter, '--check-sandbox', source, output], env=runtime_env,
            preexec_fn=filter_setup(444, errno.ENOSYS), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['policy'] == 'best_effort' and report['degraded']
        assert not report['features']['filesystem_isolation']['enabled']
        assert not output.exists()
        converted = subprocess.run([converter, source, output], env=runtime_env,
            preexec_fn=filter_setup(444, errno.EPERM), capture_output=True, text=True, timeout=60)
        assert converted.returncode == 0, converted.stderr
        assert output.read_bytes().startswith(b'%PDF-')
        assert 'filesystem_isolation' in converted.stderr
        output.unlink()
        output.symlink_to(root / 'secret')
        refused = subprocess.run([converter, source, output], env=runtime_env,
            preexec_fn=filter_setup(444, errno.EPERM), capture_output=True, text=True, timeout=60)
        assert refused.returncode != 0
        assert (root / 'secret').read_text() == 'secret'
        print('PASS: production preflight, conversion, and symlink refusal with unavailable Landlock')
