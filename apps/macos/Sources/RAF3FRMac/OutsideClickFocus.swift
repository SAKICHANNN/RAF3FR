import AppKit
import SwiftUI

private final class InitialFocusResetView: NSView {
    private var didReset = false

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard !didReset, let window else { return }
        didReset = true
        DispatchQueue.main.async { [weak window] in
            guard let window else { return }
            window.initialFirstResponder = nil
            window.makeFirstResponder(nil)
        }
    }
}

private struct InitialFocusReset: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { InitialFocusResetView() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

private struct OutsideClickFocusModifier: ViewModifier {
    @State private var mouseMonitor: Any?

    func body(content: Content) -> some View {
        content
            .onAppear {
                guard mouseMonitor == nil else { return }
                mouseMonitor = NSEvent.addLocalMonitorForEvents(matching: .leftMouseDown) { event in
                    guard let window = event.window,
                          let editor = window.firstResponder as? NSTextView,
                          editor.isFieldEditor,
                          let textField = editor.delegate as? NSTextField,
                          let contentView = window.contentView else { return event }

                    let point = contentView.convert(event.locationInWindow, from: nil)
                    let hitView = contentView.hitTest(point)
                    let clickedInsideTextField = hitView === textField
                        || (hitView?.isDescendant(of: textField) ?? false)
                    if !clickedInsideTextField {
                        window.makeFirstResponder(nil)
                    }
                    return event
                }
            }
            .onDisappear {
                if let mouseMonitor {
                    NSEvent.removeMonitor(mouseMonitor)
                    self.mouseMonitor = nil
                }
            }
    }
}

extension View {
    func dismissTextFieldOnOutsideClick() -> some View {
        background(InitialFocusReset().frame(width: 0, height: 0))
            .modifier(OutsideClickFocusModifier())
    }
}
