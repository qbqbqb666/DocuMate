#!/bin/zsh

set -u

SCRIPT_DIR="${0:A:h}"
APP_PATH="$SCRIPT_DIR/release/mac-arm64/DocuMate.app"

if [[ ! -d "$APP_PATH" ]]; then
  osascript -e 'display dialog "没有找到 DocuMate.app，请先在项目目录执行 npm run package:mac。" buttons {"知道了"} default button 1 with icon caution'
  exit 1
fi

open "$APP_PATH"
