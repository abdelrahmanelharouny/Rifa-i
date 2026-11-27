const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client;

class RifaIDebugConfigurationProvider {
  resolveDebugConfiguration(folder, configuration) {
    const editor = vscode.window.activeTextEditor;
    if (!configuration.type && editor && editor.document.languageId === "rifai") {
      configuration.type = "rifai";
      configuration.request = "launch";
      configuration.name = configuration.name || "Debug current Rifa'i file";
    }
    if (configuration.type !== "rifai") {
      return configuration;
    }
    if (!configuration.request) {
      configuration.request = "launch";
    }
    if (!configuration.program) {
      if (!editor || editor.document.languageId !== "rifai") {
        void vscode.window.showErrorMessage("Open a .rif file or set 'program' in the Rifa'i launch configuration.");
        return undefined;
      }
      configuration.program = editor.document.uri.fsPath;
    }
    return configuration;
  }
}

class RifaIDebugAdapterDescriptorFactory {
  createDebugAdapterDescriptor(session) {
    const configuration = vscode.workspace.getConfiguration("rifai");
    const command = configuration.get("serverPath", "rifai");
    const cwd = session.workspaceFolder ? session.workspaceFolder.uri.fsPath : undefined;
    return new vscode.DebugAdapterExecutable(
      command,
      ["debug-adapter"],
      { cwd }
    );
  }
}

function activate(context) {
  const configuration = vscode.workspace.getConfiguration("rifai");
  const command = configuration.get("serverPath", "rifai");

  const serverOptions = {
    command,
    args: ["lsp"],
    transport: TransportKind.stdio,
    options: {
      cwd: vscode.workspace.workspaceFolders
        ? vscode.workspace.workspaceFolders[0].uri.fsPath
        : undefined
    }
  };

  const watcher = vscode.workspace.createFileSystemWatcher("**/*.rif");
  const clientOptions = {
    documentSelector: [{ scheme: "file", language: "rifai" }],
    synchronize: { fileEvents: watcher },
    outputChannelName: "Rifa'i Language Server"
  };

  client = new LanguageClient(
    "rifai",
    "Rifa'i Language Server",
    serverOptions,
    clientOptions
  );

  const debugProvider = new RifaIDebugConfigurationProvider();
  const debugFactory = new RifaIDebugAdapterDescriptorFactory();
  context.subscriptions.push(watcher);
  context.subscriptions.push(client.start());
  context.subscriptions.push(
    vscode.debug.registerDebugConfigurationProvider("rifai", debugProvider)
  );
  context.subscriptions.push(
    vscode.debug.registerDebugAdapterDescriptorFactory("rifai", debugFactory)
  );
}

async function deactivate() {
  if (client) {
    await client.stop();
    client = undefined;
  }
}

module.exports = { activate, deactivate };
