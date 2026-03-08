import * as vscode from 'vscode';
import { SidebarProvider } from './providers/SidebarProvider';
import { GraphTabProvider } from './providers/GraphTabProvider';
import { PythonServerClient } from './providers/PythonServerClient';

export async function activate(context: vscode.ExtensionContext) {
    // testing only
    // await context.globalState.update('hasShownInstallPrompt', undefined);

    // Show installation prompt on first activation via status bar
    const hasShownInstallPrompt = context.globalState.get<boolean>('hasShownInstallPrompt');
    if (!hasShownInstallPrompt) {
        const pipCommand = 'pip install agent-copilot';

        // Status bar that stays until clicked
        const statusBarItem = vscode.window.createStatusBarItem(
            vscode.StatusBarAlignment.Right,
            1000 
        );
        statusBarItem.text = '$(terminal) Setup: pip install agent-copilot';
        statusBarItem.tooltip = 'Click to copy install command';
        statusBarItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
        statusBarItem.command = 'agentCopilot.copyInstallCommand';
        statusBarItem.show();

        // Command to handle click
        const disposable = vscode.commands.registerCommand('agentCopilot.copyInstallCommand', async () => {
            // Hide status bar when clicked
            statusBarItem.dispose();
            await context.globalState.update('hasShownInstallPrompt', true);

            const selection = await vscode.window.showInformationMessage(
                '👋 Run "pip install agent-copilot" to complete setup',
                'Copy Command',
                'Open Terminal'
            );

            if (selection === 'Copy Command') {
                await vscode.env.clipboard.writeText(pipCommand);
                vscode.window.showInformationMessage('Command copied to clipboard!');
            } else if (selection === 'Open Terminal') {
                const terminal = vscode.window.createTerminal('Agent Copilot Setup');
                terminal.show();
                terminal.sendText(pipCommand, false);
            }
        });

        context.subscriptions.push(statusBarItem, disposable);
    }

    // Create and connect the Python client
    const pythonClient = PythonServerClient.getInstance();
    await pythonClient.ensureConnected();

    // Register the sidebar provider
    const sidebarProvider = new SidebarProvider(context.extensionUri, context);

    // Register the graph tab provider
    const graphTabProvider = new GraphTabProvider(context.extensionUri);

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(SidebarProvider.viewType, sidebarProvider, {
            webviewOptions: { retainContextWhenHidden: true }
        })
    );

    context.subscriptions.push(
        vscode.window.registerWebviewPanelSerializer(GraphTabProvider.viewType, graphTabProvider)
    );

    // Connect sidebar and graph tab providers
    sidebarProvider.setGraphTabProvider(graphTabProvider);

    // Register command to show the graph
    context.subscriptions.push(
        vscode.commands.registerCommand('graphExtension.showGraph', () => {
            vscode.commands.executeCommand('graphExtension.graphView.focus');
        })
    );

}