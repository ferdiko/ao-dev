#!/bin/bash
# Build script for creating .vsix package
# This works around vsce's inability to handle our UI workspace layout
# while webpack resolves sources from the shared components package alias

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMP_DIR=$(mktemp -d)
EXTENSION_NAME="sovara"

echo "Building extension in temp directory: $TEMP_DIR"

# Step 1: Run webpack build (this compiles TypeScript and bundles everything)
echo "Running webpack build..."
npm run package

# Step 2: Remove source maps (they reference parent directories)
echo "Removing source maps..."
rm -f dist/*.map

# Step 3: Copy only the files needed for the VSIX to temp directory
echo "Copying files to temp directory..."
mkdir -p "$TEMP_DIR/extension"

# Copy dist folder (compiled JS bundles)
cp -r dist "$TEMP_DIR/extension/"

# Copy HTML templates (loaded at runtime by webview providers)
mkdir -p "$TEMP_DIR/extension/src/webview"
cp -r src/webview/templates "$TEMP_DIR/extension/src/webview/"

# Copy codicons to dist/ (vsce excludes node_modules, so we put them in dist/)
mkdir -p "$TEMP_DIR/extension/dist/codicons"
cp node_modules/@vscode/codicons/dist/codicon.css "$TEMP_DIR/extension/dist/codicons/"
cp node_modules/@vscode/codicons/dist/codicon.ttf "$TEMP_DIR/extension/dist/codicons/"

# Copy package.json and remove prepublish script (we already built)
python3 << EOF
import json
with open('package.json') as f:
    pkg = json.load(f)
pkg['scripts'] = {k: v for k, v in pkg.get('scripts', {}).items() if 'prepublish' not in k}
with open('${TEMP_DIR}/extension/package.json', 'w') as f:
    json.dump(pkg, f, indent=2)
EOF

# Copy readme for VS Code marketplace
cp ../../../docs/release/VSIX_DESC.md "$TEMP_DIR/extension/README.md"

# Copy license file from repo root
cp ../../../LICENSE "$TEMP_DIR/extension/LICENSE"

# Copy icon
cp ../../../docs/release/marketplace_icon.png "$TEMP_DIR/extension/icon.png"

# Step 4: Create a minimal .vscodeignore in temp
cat > "$TEMP_DIR/extension/.vscodeignore" << 'EOF'
**/*.map
EOF

# Step 5: Run vsce package from temp directory (skip prepublish since we already built)
echo "Creating VSIX package..."
cd "$TEMP_DIR/extension"
if ! command -v vsce >/dev/null 2>&1; then
    echo "ERROR: 'vsce' is not installed. Run 'npm install -g @vscode/vsce' from any directory and try again."
    exit 1
fi
vsce package --no-dependencies --allow-star-activation

# Step 6: Move the .vsix back to original directory
VSIX_FILE=$(ls *.vsix 2>/dev/null | head -1)
if [ -n "$VSIX_FILE" ]; then
    mv "$VSIX_FILE" "$SCRIPT_DIR/"
    echo "Created: $SCRIPT_DIR/$VSIX_FILE"
else
    echo "ERROR: No .vsix file was created"
    exit 1
fi

# Step 7: Cleanup
rm -rf "$TEMP_DIR"
echo "Done!"
