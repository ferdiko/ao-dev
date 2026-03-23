# VS Code Graph Extension

A VS Code extension that displays an interactive graph view in the sidebar with nodes and edges.

## Installation

1. Install Node.js
2. In this dir (`vscode_extension`), run `npm install`
3. Run `npm run compile` to build the extension. When developing run `npm run watch` so the extension is continuously re-compiled as you do changes.
4. From the debugger options (from `launch.json`) select "Run extension" and run.
5. A new window will open with the extension active. The graph view will appear in the Explorer sidebar.


## Usage

### Adding Nodes
The extension listens for messages from the backend. To add a node programmatically:

```javascript
// In GraphViewProvider
provider.addNode({
    id: 'unique-id',
    input: 'Input text',
    output: 'Output text',
    stack_trace: 'File "/path/to/file.py", line 42, in main',
    label: 'Node Label'
});
```

### Node Interactions
- **Hover** over a node to see the action menu
- **Edit Input**: Modify the node's input string
- **Edit Output**: Modify the node's output string
- **Change Label**: Update the node's display label
- **See in Code**: Navigate to code location
- **Document Preview**: Base64-encoded files (PDF, images, DOCX) are detected and shown as clickable buttons to open in your default app

### Backend Communication
The extension sends messages to the backend when:
- A node's input, output, or label is edited
- The webview is ready to receive data

Message format:
```typescript
{
    type: 'updateNode',
    payload: {
        nodeId: string,
        field: 'input' | 'output' | 'label',
        value: string
    }
}
```

## Dev

Some basics:

 - If you want to see the logs in the extension: `Cmd+P` and then type `> Developer: Toggle Developer Tools`. 

### Architecture

See README at project root for architecture diagram. Below might be outdated.

#### Extension <-> Webview

 - Webview send message to extension. Utilities (e.g., `sendMessage()`) in `src/webview/utils/messaging.ts`
 - Webview receive message from extension: `src/webview/App.tsx`
 - Extension receive message from webview: `src/providers/GraphViewProvider.ts`
 - Extension send to webview happens in several places using `webview.postMessage()`. For example in `GraphViewProvider.ts`

#### Extension <-> Python bridge

 - Extension receives and sends messages in `GraphViewProvider.ts` (see `_sendToPython` and `_handlePythonMessage`)

### Graph layout
We use our custom algorithm to determine where nodes are placed in the web view pannel and where edge flow between them. [The algo can be found here.](https://drive.google.com/file/d/1eKiijfvaGs_-5sajpeqk923Xbvro7x3X/view?usp=drive_link)
