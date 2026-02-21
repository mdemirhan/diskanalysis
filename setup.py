import platform

from setuptools import Extension, setup

_common_flags = ["-O3", "-DNDEBUG", "-flto"]

if platform.machine() in ("x86_64", "AMD64"):
    _common_flags += ["-march=native", "-msse4.2"]
elif platform.machine() == "arm64":
    _common_flags += ["-mcpu=native"]

setup(
    ext_modules=[
        Extension(
            "dux._walker",
            sources=["csrc/walker.c"],
            extra_compile_args=_common_flags,
            extra_link_args=["-flto"],
        ),
        Extension(
            "dux._ac_matcher",
            sources=["csrc/ac_matcher.c"],
            extra_compile_args=_common_flags,
            extra_link_args=["-flto"],
        ),
        Extension(
            "dux._prefix_trie",
            sources=["csrc/prefix_trie.c"],
            extra_compile_args=_common_flags,
            extra_link_args=["-flto"],
        ),
    ]
)
