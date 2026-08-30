import SwiftUI

@main
struct RAF3FRMacApp: App {
    @StateObject private var model: AppModel

    init() {
        _model = StateObject(wrappedValue: AppModel(defaults: AppDefaults.launch()))
        ProductTypography.registerBundledFonts()
    }

    var body: some Scene {
        Window("RAF / 3FR", id: "main") {
            RootView(model: model)
                .preferredColorScheme(.dark)
        }
        .windowResizability(.contentMinSize)
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button(model.t("openRaf"), action: model.chooseSource).keyboardShortcut("o")
            }
            CommandMenu(model.t("conversionMenu")) {
                Button(model.t("startConversion"), action: model.startConversion)
                    .keyboardShortcut(.return, modifiers: [.command])
                    .disabled(!model.canConvert)
                Button(model.t("cancel"), action: model.cancel).disabled(!model.phase.isRunning)
                Divider()
                Button(model.t("reveal"), action: model.revealLatest).disabled(model.latestOutput == nil)
                Button(model.t("openPhocus"), action: model.openLatestInPhocus).disabled(model.latestOutput == nil)
            }
        }

        Settings {
            SettingsView(model: model)
                .preferredColorScheme(.dark)
        }
        .windowStyle(.hiddenTitleBar)
    }
}
