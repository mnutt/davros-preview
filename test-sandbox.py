#!/usr/bin/env python3
"""Build sandbox-check first; accepts its path. Uses no private documents."""
import ctypes
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
    (root / 'scratch/preview.pdf').unlink()

    # Simulate a host that denies Landlock, without weakening the application.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte), ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    def deny_landlock():
        # landlock_create_ruleset is syscall 444 on Linux x86_64 and aarch64.
        filters = (Filter * 4)(Filter(0x20, 0, 0, 0), Filter(0x15, 0, 1, 444),
                              Filter(0x06, 0, 0, 0x50000 | 38), Filter(0x06, 0, 0, 0x7fff0000))
        program = Program(4, filters)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
            raise OSError(ctypes.get_errno(), 'test seccomp setup failed')
    failure = subprocess.run(args, env=env, preexec_fn=deny_landlock, capture_output=True, text=True)
    assert failure.returncode != 0, failure
    assert 'Preview sandbox unavailable' in failure.stderr, failure.stderr
    assert not (root / 'scratch/preview.pdf').exists()
    print('PASS: unavailable Landlock fails closed before producing output')
