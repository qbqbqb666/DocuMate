from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH)
datas = []
binaries = []
hiddenimports = []

for package in (
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
