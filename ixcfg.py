import os
import os.path
import re
from ix import has_to_recompile as ix_has_to_recompile, compile_file
from ix.utils import index_of, replace_ext
import subprocess

DEBUG_EXTERNS = {
    "porus": os.path.join(ROOTDIR, "target/debug/libporus.rlib"),
    "porus_macros": os.path.join(ROOTDIR, "target/debug/libporus_macros.so"),
}
SOLUTION_PATTERN = r'^(?:[^/]+)/(?P<oj>\w+)(?:/.*)?/(?P<problem>[A-Za-z0-9_\-]+)\.rs(?:\.c)?$'


def extern(externs):
    return sum([['--extern', '{}={}'.format(k,v)] for k,v in externs.items()], [])


def has_to_recompile(source, target, rlibs=DEBUG_EXTERNS):
    if ix_has_to_recompile(source, target):
        return True

    rlib = rlibs["porus"]
    if os.stat(rlib).st_mtime >= os.stat(target).st_mtime:
        return True

    return False


def get_rustc_argv(mode='debug', target=None):
    EXTERNS = {
        "porus": os.path.join(ROOTDIR, "target/{}{}/libporus.rlib".format("" if target is None else target+"/", mode)),
        "porus_macros": os.path.join(ROOTDIR, "target/{}/libporus_macros.so".format(mode)),
    }
    DEPS = ['-L', 'dependency='+os.path.join(ROOTDIR, "target/{}/deps".format(mode))]

    VERBOSE_FLAG = '-v' if VERBOSE else '-q'
    MODE = [] if mode == 'debug' else ['--'+mode]
    TARGET = [] if target is None else ['--target', target]

    ARGV = ['cargo', 'build', VERBOSE_FLAG, '--lib'] + MODE + TARGET
    if compile_file(ROOTDIR, ARGV, 'PORUS LIB', EXTERNS["porus"]) is None:
        return

    FLAGS = os.environ.get("RUSTFLAGS", "-Z borrowck=mir -Z polonius").split(" ")
    DEBUG = ['-C', 'debuginfo=2'] if mode == 'debug' else []
    return ['rustc', '-Z', 'external-macro-backtrace'] + DEBUG + FLAGS + DEPS, EXTERNS


def get_compile_argv(filename):
    target = replace_ext(filename,"elf")

    if filename.endswith(".c"):
        return ['gcc', '-o', target, filename], target

    argv, externs = get_rustc_argv()
    if argv is None:
        raise Exception("failed to build library")

    return argv + extern(externs) + ['-o', target, filename], target


def list_generated_files(filename):
    return [replace_ext(filename, ext) for ext in ["elf","bc","ll","s","rs.c","rs.elf","gcno","gcda"]]


def pick_env(envs):
    envs = [c for c in envs if c.lang == "C" and c.name in ("GCC", "MinGW")]
    envs.sort(key=lambda c: (index_of(['Linux','Windows'], c.os), index_of(['x86_64','x86'], c.arch)))
    if envs:
        return envs[0]


def get_llvm_target(env):
    return ( ({"x86": "i686", "x86_64": "x86_64"}[env.arch])
             + "-" +
             ({"Windows": "pc-windows", "Linux": "unknown-linux"}[env.os]) + "-gnu")


def generate_submission(source, llvm_target):
    argv, externs = get_rustc_argv('release', llvm_target)
    target = replace_ext(source, "s")

    argv = argv + extern(externs) + [
        "--crate-type", "cdylib",
        "--emit", "asm",
        "-C", "llvm-args=-disable-debug-info-print",
        "-C", "lto=fat",
        "-C", "opt-level=s",
        "-C", "panic=abort",
        "-o", target, source]

    if has_to_recompile(source, target, externs):
        if compile_file(ROOTDIR, argv, source, target) is None:
            return None

    return target

GLOBL = re.compile(rb'^\s+[.]globl\s+(\S+)$', re.M)
LABEL = re.compile(rb'^([^:\s]+):$', re.M)
CHARS = b'_.0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'

def encode_int(n):
    while True:
        yield CHARS[n % 64]
        if n == 0:
            break
        n //= 64

def prepare_submission(envs, filename):
    env = pick_env(envs)
    if not env:
        return None

    llvm_target = get_llvm_target(env)

    if filename.endswith(".c"):
        llvm_target = None
        filename = filename[:-2]

    asm = generate_submission(filename, llvm_target)
    if asm is None:
        return None

    with open(asm,'rb') as f:
        code = f.read()

    labels = set(LABEL.findall(code)) - set(GLOBL.findall(code))
    # labels.discard(b"main")
    # labels.discard(b"_main")
    pattern = b"|".join(map(re.escape, labels))
    labels = {l: b"L"+bytes(encode_int(n))
              for n,l in enumerate(labels)}
    def repl(m):
        return labels[m.group(0)]
    code = re.sub(pattern, repl, code)

    if llvm_target is None:
        from ix.escape import escape_source
        code1 = escape_source(code)
        with open(filename+".c",'wb') as f:
            f.write(code1)

    return env, code
