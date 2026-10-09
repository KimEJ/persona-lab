import AppKit

enum NativeLifecycleProbe {
    static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        let home = URL(fileURLWithPath: ProcessInfo.processInfo.environment["PERSONA_LAB_HOME"]!)
        let ready = ProcessInfo.processInfo.environment["LIFECYCLE_READY"] == "1"
        var closing = false
        var checking = false
        var hiddenWindow: NSWindow?
        let timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in
            guard !closing, !checking, delegate.worker?.isRunning == true,
                  FileManager.default.fileExists(atPath: home.appendingPathComponent("worker.json").path) else { return }
            let close = {
                closing = true
                // A report's hidden host window must not keep the app running.
                hiddenWindow = NSWindow(contentRect: .zero, styleMask: .borderless, backing: .buffered, defer: false)
                hiddenWindow?.isReleasedWhenClosed = false
                delegate.window.performClose(nil)
            }
            if !ready {
                close()
                return
            }
            guard delegate.endpoint != nil else { return }
            checking = true
            delegate.webView.evaluateJavaScript("Boolean(window.appCommands)") { value, _ in
                checking = false
                if value as? Bool == true { close() }
            }
        }
        application.run()
        timer.invalidate()
        withExtendedLifetime(hiddenWindow) {}
    }
}
