"""按参考目录「主题一-创意方案-ClubCopilot社团智脑-李政寰-2024级数字媒体技术班」结构组装桌面投稿包。

输出结构：
  Desktop/主题一-创意方案-楚师智学-李政寰-2024级数字媒体技术班/
    ├── 参赛报名及作品信息表（附件1）.docx
    ├── 作品提交清单与自查说明（附件2）.docx
    ├── 原创承诺书及AI工具使用声明（附件3）.docx
    ├── 创作过程记录.docx
    └── 作品本体/
        ├── 创意方案书/
        │   └── 楚师智学_创意方案书.pdf
        ├── 原型演示视频/
        ├── 可演示原型与云盘链接/
        │   ├── 可演示原型说明与移动云盘链接.txt
        │   ├── MaoLog_独立便携版/MaoLog_便携版.exe
        │   └── 源码与MobileClaw技能包/
        └── 界面原型截图展示/
            ├── 01_手帐主看板_时间轴与分类占比.png
            ├── ...
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SUBMIT = DOCS / "参赛提交材料"

FOLDER_NAME = "主题一-创意方案-楚师智学-李政寰-2024级数字媒体技术班"
TARGET_DIR = Path.home() / "Desktop" / FOLDER_NAME

PROTOTYPE_README = """========================================================================
楚师智学（MaoLog）· 可演示原型运行说明与移动云盘访问指引
========================================================================

一、直接免环境运行（推荐评委使用）
1. 进入同目录下的「MaoLog_独立便携版」文件夹（或从下方云盘下载独立便携版）；
2. 双击「MaoLog_便携版.exe」即可启动手帐风主看板与蘑菇小精灵桌宠；
3. 无需安装 Python 或填写任何 API Key，程序默认启用「本地免 Key 模式」自动识别
   活动并支持点击右下角「演示看板」按钮一键预览隔离的 v2 学习复盘完整数据。

   * 如需体验在线大模型：点击看板「设置 -> AI 接入」，选择通义千问 / 智谱 GLM-4V /
     兼容 OpenAI 格式接口，填入中国移动 MobileClaw 或模型 Key 即可切换至在线识别。

二、中国移动云盘大文件访问链接（提交超限备份用）
- 原型可执行程序包与高清演示视频云盘链接：【请在此处填写您的中国移动云盘分享链接】
- 提取码：【请在此处填写提取码或“无需提取码”】

三、源码与 MobileClaw 技能包运行方式（开发者/技术复核）
- 同级目录「源码与MobileClaw技能包」含完整 core/ 引擎层、ui/ 手帐双界面层及
  mobileclaw_skill/chushi-zhixue-bridge/ 脱敏桥接技能包；
- 执行全量离线自动化测试：
    python tools/test_startup.py
    python tools/test_fixes.py
    python tools/test_v2.py
- 导出面向 MobileClaw 的脱敏复盘 JSON：
    python mobileclaw_skill/chushi-zhixue-bridge/scripts/export_bridge.py
========================================================================
"""

VIDEO_NOTE = """请将录制的演示视频重命名为「楚师智学_原型演示视频_1080P.mp4」放入本目录。

技术规范核对：
- 时长：不超过 3 分钟（推荐 2 分 30 秒 ~ 2 分 55 秒）
- 画幅与编码：1920×1080（16:9 横屏），30fps，MP4（H.264），码率 ≥ 8Mbps，体积 ≤ 500MB
- 字幕与水印：全片配简体中文字幕，片头标作品名与参赛主题，片尾标主创/学院/AI工具，无第三方水印
"""


def copy_tree_clean(src: Path, dst: Path) -> None:
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
        dirs_exist_ok=True,
    )


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 根目录放 4 份可编辑 Word（不放不可编辑 PDF，由参赛者签字/补图后自行导出 PDF）
    root_docx_map = [
        ("附件1-参赛报名及作品信息表", "参赛报名及作品信息表（附件1）"),
        ("附件2-作品提交清单与自查说明", "作品提交清单与自查说明（附件2）"),
        ("附件3-原创承诺书及AI工具使用声明", "原创承诺书及AI工具使用声明（附件3）"),
        ("创作过程记录", "创作过程记录"),
    ]
    for src_stem, dst_stem in root_docx_map:
        src = SUBMIT / f"{src_stem}.docx"
        if src.exists():
            shutil.copy2(src, TARGET_DIR / f"{dst_stem}.docx")

    # 2. 作品本体四子目录（1:1 对齐参考目录结构，保留已生成的演示视频）
    body_dir = TARGET_DIR / "作品本体"
    plan_dir = body_dir / "创意方案书"
    video_dir = body_dir / "原型演示视频"
    proto_dir = body_dir / "可演示原型与云盘链接"
    shots_dir = body_dir / "界面原型截图展示"
    for d in (plan_dir, video_dir, proto_dir, shots_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 2.1 创意方案书（直接提交终稿 PDF）
    shutil.copy2(DOCS / "楚师智学-参赛方案说明书.pdf", plan_dir / "楚师智学_创意方案书.pdf")

    # 2.2 若尚未生成 1080P 视频才写入引导，否则保持视频目录纯净
    if not (video_dir / "楚师智学_原型演示视频_1080P.mp4").exists():
        shutil.copy2(SUBMIT / "演示视频脚本与拍摄清单(3分钟内).md", video_dir / "演示视频脚本与拍摄清单(3分钟内).md")
        (video_dir / "视频放入说明.txt").write_text(VIDEO_NOTE, encoding="utf-8")

    # 2.3 可演示原型与云盘链接
    (proto_dir / "可演示原型说明与移动云盘链接.txt").write_text(PROTOTYPE_README, encoding="utf-8")
    exe_src = ROOT / "dist" / "MaoLog_便携版.exe"
    if exe_src.exists():
        exe_dir = proto_dir / "MaoLog_独立便携版"
        exe_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exe_src, exe_dir / "MaoLog_便携版.exe")

    src_dir = proto_dir / "源码与MobileClaw技能包"
    src_dir.mkdir(parents=True, exist_ok=True)
    for fn in ("main.py", "requirements.txt", "README.md"):
        if (ROOT / fn).exists():
            shutil.copy2(ROOT / fn, src_dir / fn)
    for folder in ("core", "ui", "assets", "mobileclaw_skill"):
        if (ROOT / folder).exists():
            copy_tree_clean(ROOT / folder, src_dir / folder)

    # 2.4 界面原型截图展示（精选 6 张实机渲染截图）
    shot_pairs = [
        (ROOT / "assets" / "figures" / "fig5_dashboard.png", "01_手帐主看板_时间轴与分类占比.png"),
        (ROOT / "data" / "v2_preview" / "v2_预览_学习复盘.png", "02_学习过程复盘_节奏诊断与报告导出.png"),
        (ROOT / "data" / "v2_preview" / "v2_预览_AI协作回看.png", "03_AI协作画像_思考与提问边界回看.png"),
        (ROOT / "data" / "v2_preview" / "v2_预览_数据护照.png", "04_数据护照与外发台账_隐私通行证.png"),
        (ROOT / "data" / "v2_preview" / "v2_预览_估时校准.png", "05_估时校准_计划与产出偏差对照.png"),
        (ROOT / "data" / "v2_preview" / "preview_tab_0.png", "06_设置中心_AI接入与本地免Key模式.png"),
    ]
    for src, dst_name in shot_pairs:
        if src.exists():
            shutil.copy2(src, shots_dir / dst_name)

    print(f"已按 ClubCopilot 主题一参考目录结构生成 -> {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
