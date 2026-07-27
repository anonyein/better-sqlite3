#!/usr/bin/env python3
"""Patch binding.gyp so better-sqlite3 can be cross-compiled for Android.

better-sqlite3 is a Node-API (node-addon-api) addon. On a normal desktop
prebuild the `napi_*` C-ABI symbols are left undefined and resolved by the
host Node at load time. On Android, `System.loadLibrary` uses RTLD_LOCAL, so
the host's napi symbols are not guaranteed to be globally visible to the
addon. We therefore link the addon directly against the prebuilt Javet Node
runtime shared library (which exports the full napi_* / node_api_* C ABI, plus
V8/node symbols) and add an rpath so it is found next to the .node at runtime.

This mirrors the approach used for isolated-vm and lets us keep
`-Wl,--no-undefined` on, turning any unresolved symbol into a link-time error
instead of a runtime crash.

This script is idempotent.

Environment:
  IV_ANDROID_ABI  Android ABI dir under libs/ (e.g. arm64-v8a, x86_64)
  IV_ANDROID_SO   basename of the Javet .so to link against
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GYP = os.path.join(ROOT, "binding.gyp")

ABI = os.environ.get("IV_ANDROID_ABI", "").strip()
SO = os.environ.get("IV_ANDROID_SO", "").strip()

if not ABI or not SO:
    sys.exit("IV_ANDROID_ABI and IV_ANDROID_SO must be set")

so_path = os.path.join("libs", ABI, SO).replace(os.sep, "/")
abs_so = os.path.join(ROOT, "libs", ABI, SO)
if not os.path.isfile(abs_so):
    sys.exit(f"Javet .so not found: {abs_so}")

with open(GYP, "r", encoding="utf-8") as f:
    src = f.read()

if "IV_ANDROID_PATCH" in src:
    print("binding.gyp already patched; skipping")
    sys.exit(0)

# The better_sqlite3 target defines a linux-only block:
#     'conditions': [['OS=="linux"', {
#       'ldflags': ['-flto', '-Wl,-Bsymbolic', '-Wl,--exclude-libs,ALL'],
#       'libraries': ['-ldl'],
#     }]],
# When cross-compiling on a Linux host, gyp's OS variable is "linux", so this
# block is what actually applies. Rewrite it to also link the Javet .so, add
# an rpath, and enforce --no-undefined.
old_block = (
    "'conditions': [['OS==\"linux\"', {\n"
    "            'ldflags': ['-flto', '-Wl,-Bsymbolic', '-Wl,--exclude-libs,ALL'],\n"
    "            'libraries': ['-ldl'],\n"
    "          }]],"
)

new_block = (
    "'conditions': [['OS==\"linux\"', {\n"
    "            # IV_ANDROID_PATCH: link directly against the bundled Javet Node\n"
    "            # runtime .so (exports the full napi_*/node_api_* C ABI) so the\n"
    "            # Android addon resolves N-API at link time, not runtime.\n"
    "            'ldflags': [\n"
    "              '-flto',\n"
    "              '-Wl,-Bsymbolic',\n"
    "              '-Wl,--exclude-libs,ALL',\n"
    "              '-Wl,--no-undefined',\n"
    "              \"-Wl,-rpath,'$$ORIGIN'\",\n"
    "            ],\n"
    "            'libraries': [\n"
    "              '-ldl',\n"
    f"              '<(module_root_dir)/{so_path}',\n"
    "            ],\n"
    "          }]],"
)

if old_block not in src:
    sys.exit("could not find better_sqlite3 linux conditions block to patch")

src = src.replace(old_block, new_block, 1)

with open(GYP, "w", encoding="utf-8") as f:
    f.write(src)

print(f"patched binding.gyp: link -> {so_path}")
