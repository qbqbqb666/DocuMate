from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH)
datas = []
binaries = []
hiddenimports = []

for package in (
    "sqlite_vec",
    "onnxruntime",
    "tokenizers",
    "docx",
    "langchain",
    "langchain_core",
    "langchain_deepseek",
    "langchain_openai",
    "langgraph",
    "langgraph_checkpoint",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

MODEL_ROOT = ROOT / "src" / "backend" / "data" / "models" / "multilingual-e5-small"
for required in ("model.onnx", "tokenizer.json"):
    if not (MODEL_ROOT / required).is_file():
        raise RuntimeError(f"打包缺少本地 E5 资源：{MODEL_ROOT / required}")
# 只携带模型目录直属资源，不包含下载的依赖 wheel 和测试资料。
datas += [(str(resource), "models/multilingual-e5-small") for resource in MODEL_ROOT.iterdir() if resource.is_file()]

a = Analysis(
    [str(ROOT / "src" / "backend" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    module_collection_mode={"docx": "pyz+py"},
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "IPython", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="documate-backend", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="documate-backend")
