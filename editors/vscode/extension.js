const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client;

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

  context.subscriptions.push(watcher);
  context.subscriptions.push(client.start());
}

async function deactivate() {
  if (client) {
    await client.stop();
    client = undefined;
  }
}

module.exports = { activate, deactivate };
