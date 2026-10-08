# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
# 上面这条得有：本文件的 import 是运行时才成立的，config / src 只有在
# sys.path 上追加了 task2 目录之后才解析得到，静态分析器看不到。
# 真正的保护是下面 _assert_from_task2 的运行时断言。
"""把任务二的工程当依赖加载，「实时接入」只在这一个文件里。

为什么要这层：任务二的模块内部用的是顶层绝对导入（import config、
from src.tag_detect import ...），要用它们就得让 task2 目录进 sys.path，
而且顶层名字 config、src 得解析到 task2。这带来两个同名遮蔽的坑：

    task2 有顶层模块 config → 本工程的配置因此叫 t3config
    task2 有顶层包   src    → 本工程的包因此叫 cvlink

名字撞上时 Python 不报错，只会静默导入对面那个模块，结果全错。
所以加载完立刻断言 config / src 确实来自 task2 目录，撞名就当场失败。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]              # task3/
DEFAULT_TASK2_DIR = ROOT.parent / "task2"


class Task2ImportError(RuntimeError):
    """找不到任务二工程，或它的模块被同名模块遮蔽。"""


def load_task2(task2_dir: str | Path | None = None) -> SimpleNamespace:
    """导入并按名字暴露任务二要用到的接口。"""
    directory = Path(task2_dir or DEFAULT_TASK2_DIR).expanduser().resolve()
    if not (directory / "config.py").exists():
        raise Task2ImportError(f"找不到任务二工程：{directory}"
                               f"（用 --task2-dir 指定 task2 目录）")

    if str(directory) not in sys.path:
        # 追加到末尾：本工程自己的模块优先解析，任务二只提供 config / src 这两个名字
        sys.path.append(str(directory))

    try:
        import config as t2config
        from src import calibration as t2calibration
        from src import camera as t2camera
        from src import undistort as t2undistort
        from src.pipeline import PosePipeline
    except ImportError as e:
        raise Task2ImportError(f"导入任务二模块失败：{e}") from e

    _assert_from_task2(t2config, directory, "config")
    _assert_from_task2(t2camera, directory, "src.camera")
    _assert_from_task2(t2calibration, directory, "src.calibration")
    _assert_from_task2(t2undistort, directory, "src.undistort")
    _assert_from_task2(sys.modules["src.pipeline"], directory, "src.pipeline")

    return SimpleNamespace(
        dir=directory,
        config=t2config,
        Camera=t2camera.Camera,
        CameraError=t2camera.CameraError,
        Undistorter=t2undistort.Undistorter,
        load_params=t2calibration.load_params,
        PosePipeline=PosePipeline,
    )


def _assert_from_task2(module, task2_dir: Path, what: str) -> None:
    path = Path(module.__file__).resolve()
    if task2_dir not in path.parents:
        raise Task2ImportError(
            f"{what} 解析到了 {path}，不在 {task2_dir} 之下，"
            f"说明 task3 里出现了同名的模块或包（如 config.py 或 src/）。"
            f"把它们改名（本工程用 t3config / cvlink）即可。")
