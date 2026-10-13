#!/bin/zsh -l

set -euo pipefail

finish() {
  local exit_code="$1"
  if (( exit_code != 0 )); then
    print "打包失败，请查看上方错误。"
  fi
  if [[ -t 0 ]]; then
    read -r "?按回车关闭窗口…"
  fi
}
trap 'finish $?' EXIT

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  print "请在 Apple Silicon Mac 上运行此脚本。"
  exit 1
fi
for tool in node npm uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    print "未找到 $tool，请先安装并确保终端可以运行。"
    exit 1
  fi
done

export NPM_CONFIG_REGISTRY="https://registry.npmmirror.com/"
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
export UV_DEFAULT_INDEX="https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/"

VERSION="$(node -p "JSON.parse(require('fs').readFileSync('package.json', 'utf8')).version")"
OUTPUT_DIR="$PROJECT_DIR/release/mac-arm64"
APP_PATH="$OUTPUT_DIR/DocuMate.app"
ZIP_NAME="DocuMate-v${VERSION}-mac-arm64-updates.zip"
ZIP_TEMP="$OUTPUT_DIR/${ZIP_NAME}.tmp"

print "安装依赖并构建 DocuMate v${VERSION}（macOS arm64）…"
npm ci --include=dev
uv sync --frozen
npm run package:mac -- --arm64

APP_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_PATH/Contents/Info.plist")"
if [[ "$APP_VERSION" != "$VERSION" ]]; then
  print "应用版本不匹配：预期 $VERSION，实际 $APP_VERSION。"
  exit 1
fi
for binary in "$APP_PATH/Contents/MacOS/DocuMate" \
              "$APP_PATH/Contents/Resources/backend/documate-backend/documate-backend"; do
  if [[ "$(/usr/bin/lipo -archs "$binary")" != "arm64" ]]; then
    print "构建架构不匹配：$binary"
    exit 1
  fi
done

print "生成 ZIP 并检查完整性…"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP_PATH" "$ZIP_TEMP"
/usr/bin/unzip -t "$ZIP_TEMP" | /usr/bin/tail -n 1
mv -f "$ZIP_TEMP" "$OUTPUT_DIR/$ZIP_NAME"
(
  cd "$OUTPUT_DIR"
  /usr/bin/shasum -a 256 "$ZIP_NAME" > "${ZIP_NAME}.sha256.tmp"
  mv -f "${ZIP_NAME}.sha256.tmp" "${ZIP_NAME}.sha256"
)
node - "$OUTPUT_DIR" "$VERSION" <<'JS'
const fs = require('fs');
const path = require('path');
const target = path.join(process.argv[2], 'mac-version.json');
fs.writeFileSync(target + '.tmp', JSON.stringify({ version: process.argv[3], notes: '' }, null, 2) + '\n');
fs.renameSync(target + '.tmp', target);
JS

print "打包完成：$OUTPUT_DIR"
print "应用：DocuMate.app"
print "上传用 ZIP：$ZIP_NAME"
print "校验文件：${ZIP_NAME}.sha256"
print "Mac 版本提示文件：mac-version.json（上传 ZIP 后再发布）"
