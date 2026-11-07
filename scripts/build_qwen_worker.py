"""构建固定 llama.cpp 的常驻配音程序，并复用已安装的原生运行库。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


def main() -> None:
    """处理：下载固定源码并编译常驻配音程序。
    输入：构建目录、现成原生运行库目录和安装目录。
    输出：可由配音模块直接发现的本地 worker。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    source = args.work_dir / "llama.cpp-b11981"
    if not source.exists():
        archive = args.work_dir / "llama-b11981.zip"
        if not archive.exists():
            urllib.request.urlretrieve(
                "https://codeload.github.com/ggml-org/llama.cpp/zip/refs/tags/b11981", archive
            )
        with zipfile.ZipFile(archive) as package:
            package.extractall(args.work_dir)
    worker = Path(__file__).resolve().parents[1] / "src/signaltrail/native/qwen_worker.cpp"
    cmake = source / "tools/tts/CMakeLists.txt"
    cmake.write_text(
        'add_executable(llama-tts-worker "'
        + worker.as_posix()
        + '")\n'
        + "target_link_libraries(llama-tts-worker PRIVATE llama llama-common mtmd)\n"
        + "target_compile_features(llama-tts-worker PRIVATE cxx_std_17)\n",
        encoding="utf-8",
    )
    build = args.work_dir / "build"
    subprocess.run(
        [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build),
            "-DGGML_VULKAN=OFF",
            "-DGGML_BACKEND_DL=ON",
            "-DGGML_NATIVE=OFF",
            "-DLLAMA_CURL=OFF",
            "-DLLAMA_BUILD_TESTS=OFF",
            "-DCMAKE_BUILD_RPATH=" + ("@loader_path" if sys.platform == "darwin" else "$ORIGIN"),
        ],
        check=True,
    )
    subprocess.run(
        [
            "cmake",
            "--build",
            str(build),
            "--config",
            "Release",
            "--target",
            "llama-tts-worker",
            "--parallel",
            "8",
        ],
        check=True,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for library in args.runtime_dir.rglob("*"):
        if not library.is_file() or not (
            library.suffix in {".dll", ".dylib"} or ".so" in library.name
        ):
            continue
        shutil.copy2(library, args.output_dir / library.name)
    executable = next(
        build.rglob("llama-tts-worker.exe" if os.name == "nt" else "llama-tts-worker")
    )
    shutil.copy2(executable, args.output_dir / executable.name)
    print(args.output_dir / executable.name)


if __name__ == "__main__":
    main()
