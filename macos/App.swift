import AppKit
import WebKit
import UniformTypeIdentifiers

final class NativePDFExporter: NSObject, WKNavigationDelegate {
    private var webView: WKWebView?
    private var hostWindow: NSWindow?
    private var printOperation: NSPrintOperation?
    private var temporaryURL: URL?
    private var timeout: DispatchWorkItem?
    private let destination: URL
    private let completion: (Error?) -> Void
    private var finished = false

    init(html: String, destination: URL, completion: @escaping (Error?) -> Void) {
        self.destination = destination
        self.completion = completion
        super.init()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.defaultWebpagePreferences.allowsContentJavaScript = false
        let view = WKWebView(frame: NSRect(x: 0, y: 0, width: 794, height: 1123), configuration: config)
        view.navigationDelegate = self
        webView = view
        let host = NSWindow(contentRect: view.frame, styleMask: .borderless, backing: .buffered, defer: false)
        host.isReleasedWhenClosed = false
        host.contentView = view
        hostWindow = host
        let deadline = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            self.finish(self.error("보고서 변환 시간이 초과되었습니다."))
        }
        timeout = deadline
        DispatchQueue.main.asyncAfter(deadline: .now() + 45, execute: deadline)
        let rules = #"[{"trigger":{"url-filter":".*"},"action":{"type":"block"}}]"#
        WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "persona-lab-report-offline", encodedContentRuleList: rules) { [weak self] list, error in
            guard let self = self, !self.finished else { return }
            guard let list = list else { self.finish(error ?? self.error("보고서 보안 설정을 적용하지 못했습니다.")); return }
            view.configuration.userContentController.add(list)
            view.loadHTMLString(html, baseURL: nil)
        }
    }

    private func error(_ message: String) -> NSError {
        NSError(domain: "PersonaLab.PDF", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }

    private func finish(_ error: Error?) {
        guard !finished else { return }
        finished = true
        timeout?.cancel()
        webView?.stopLoading()
        webView?.navigationDelegate = nil
        webView = nil
        hostWindow?.close()
        hostWindow = nil
        printOperation = nil
        if let temporaryURL = temporaryURL { try? FileManager.default.removeItem(at: temporaryURL) }
        completion(error)
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        decisionHandler(navigationAction.targetFrame?.isMainFrame == true && navigationAction.request.url?.absoluteString == "about:blank" ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self, !self.finished else { return }
            let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("persona-report-\(UUID().uuidString).pdf")
            self.temporaryURL = temporary
            let info = NSPrintInfo(dictionary: [:])
            info.paperSize = NSSize(width: 595.276, height: 841.89)
            info.orientation = .portrait
            info.leftMargin = 36; info.rightMargin = 36
            info.topMargin = 36; info.bottomMargin = 36
            info.horizontalPagination = .fit
            info.verticalPagination = .automatic
            info.isHorizontallyCentered = false
            info.isVerticallyCentered = false
            info.jobDisposition = .save
            info.dictionary()[NSPrintInfo.AttributeKey.jobSavingURL] = temporary
            let operation = webView.printOperation(with: info)
            operation.showsPrintPanel = false
            operation.showsProgressPanel = false
            operation.canSpawnSeparateThread = true
            self.printOperation = operation
            guard let host = self.hostWindow else { self.finish(self.error("보고서 변환 창을 준비하지 못했습니다.")); return }
            operation.runModal(for: host, delegate: self, didRun: #selector(self.printOperationDidRun(_:success:contextInfo:)), contextInfo: nil)
        }
    }

    @objc private func printOperationDidRun(_ operation: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?) {
        DispatchQueue.main.async { [self] in
            completePrint(success: success)
        }
    }

    private func completePrint(success: Bool) {
        guard !finished else {
            if let temporaryURL = temporaryURL { try? FileManager.default.removeItem(at: temporaryURL) }
            return
        }
        guard success, let temporary = temporaryURL else { finish(error("PDF 보고서를 만들지 못했습니다.")); return }
        do {
            let data = try Data(contentsOf: temporary)
            guard data.starts(with: Data("%PDF-".utf8)) else { throw error("올바른 PDF 보고서가 생성되지 않았습니다.") }
            try data.write(to: destination, options: .atomic)
            finish(nil)
        } catch { finish(error) }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { finish(error) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { finish(error) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { finish(error("보고서 변환기가 종료되었습니다.")) }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WKWebView!
    var worker: Process?
    var endpoint: URL?
    var waitingToQuit = false
    var serverLog: FileHandle?
    var stdoutBuffer = Data()
    var exportInProgress = false
    var pdfExporter: NativePDFExporter?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "native")
        config.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1220, height: 860), styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView], backing: .buffered, defer: false)
        window.title = "Paneloom"
        window.backgroundColor = NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
                ? NSColor(srgbRed: 16.0 / 255, green: 29.0 / 255, blue: 37.0 / 255, alpha: 1)
                : NSColor(srgbRed: 244.0 / 255, green: 243.0 / 255, blue: 239.0 / 255, alpha: 1)
        }
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.minSize = NSSize(width: 900, height: 650)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = webView
        window.center()
        makeMenus()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startService()
    }

    func makeMenus() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Paneloom 정보", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(withTitle: "설정…", action: #selector(settings), keyEquivalent: ",")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Paneloom 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let fileItem=NSMenuItem();menu.addItem(fileItem)
        let fileMenu=NSMenu(title:"파일");fileItem.submenu=fileMenu
        fileMenu.addItem(withTitle:"새 실험",action:#selector(newExperiment),keyEquivalent:"n")
        fileMenu.addItem(withTitle:"설정 가져오기…",action:#selector(importSettings),keyEquivalent:"o")
        fileMenu.addItem(withTitle:"저장",action:#selector(save),keyEquivalent:"s")
        fileMenu.addItem(.separator())
        fileMenu.addItem(withTitle:"창 닫기",action:#selector(NSWindow.performClose(_:)),keyEquivalent:"w")
        let editItem=NSMenuItem();menu.addItem(editItem)
        let edit=NSMenu(title:"편집");editItem.submenu=edit
        edit.addItem(withTitle:"실행 취소",action:#selector(undo),keyEquivalent:"z")
        let redo=edit.addItem(withTitle:"다시 실행",action:#selector(redo),keyEquivalent:"Z")
        redo.keyEquivalentModifierMask=[.command,.shift]
        edit.addItem(.separator())
        edit.addItem(withTitle:"오려두기",action:#selector(NSText.cut(_:)),keyEquivalent:"x")
        edit.addItem(withTitle:"복사",action:#selector(NSText.copy(_:)),keyEquivalent:"c")
        edit.addItem(withTitle:"붙여넣기",action:#selector(NSText.paste(_:)),keyEquivalent:"v")
        edit.addItem(withTitle:"모두 선택",action:#selector(NSText.selectAll(_:)),keyEquivalent:"a")
        NSApp.mainMenu=menu
    }

    func command(_ name: String) { webView.evaluateJavaScript("window.appCommands?.\(name)()",completionHandler:nil) }
    @objc func newExperiment(){command("newExperiment")}
    @objc func importSettings(){command("importSettings")}
    @objc func save(){command("save")}
    @objc func undo(){command("undo")}
    @objc func redo(){command("redo")}
    @objc func settings(){command("settings")}
    @objc func about(){NSApp.orderFrontStandardAboutPanel(options:[.applicationName:"Paneloom",.applicationVersion:Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.8.1"])}

    func startService() {
        guard let resources=Bundle.main.resourceURL else { fail("앱 실행 파일을 찾을 수 없습니다."); return }
        // Keep the established directory so the new visible name retains saved experiments.
        let home = ProcessInfo.processInfo.environment["PERSONA_LAB_HOME"].map { URL(fileURLWithPath:$0,isDirectory:true) } ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Persona Lab",isDirectory:true)
        do {
            try FileManager.default.createDirectory(at:home,withIntermediateDirectories:true)
            let logURL=home.appendingPathComponent("app.log")
            if !FileManager.default.fileExists(atPath:logURL.path){FileManager.default.createFile(atPath:logURL.path,contents:nil)}
            serverLog=try FileHandle(forWritingTo:logURL);try serverLog?.seekToEnd()
            let process=Process()
            process.executableURL=Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/PythonRunner")
            process.arguments=["-s","-m","persona_desktop.server","--root",resources.path,"--home",home.path]
            var env=ProcessInfo.processInfo.environment
            env.removeValue(forKey: "__PYVENV_LAUNCHER__")
            env["PYTHONHOME"]=Bundle.main.bundleURL.appendingPathComponent("Contents/Frameworks/Python.framework/Versions/3.12").path
            env["PYTHONPATH"]=resources.appendingPathComponent("src").path
            env["PYTHONNOUSERSITE"]="1";env["PYTHONDONTWRITEBYTECODE"]="1"
            process.environment=env
            process.currentDirectoryURL=resources
            let output=Pipe();process.standardOutput=output;process.standardError=serverLog
            output.fileHandleForReading.readabilityHandler={ [weak self] handle in
                let bytes=handle.availableData
                guard !bytes.isEmpty else {handle.readabilityHandler=nil;return}
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    self.stdoutBuffer.append(bytes)
                    while let end = self.stdoutBuffer.firstIndex(of: 10) {
                        let line = self.stdoutBuffer.prefix(upTo: end)
                        self.stdoutBuffer.removeSubrange(...end)
                        guard let value = try? JSONSerialization.jsonObject(with: line) as? [String:String], let text=value["url"],let url=URL(string:text) else {continue}
                        self.endpoint=url
                        self.webView.load(URLRequest(url:url))
                    }
                }
            }
            process.terminationHandler={ [weak self] task in
                DispatchQueue.main.async {
                    if self?.waitingToQuit != true {self?.fail("앱 실행기가 종료되었습니다. 앱을 다시 실행하세요.")}
                }
            }
            worker=process
            try process.run()
        } catch { fail("앱을 시작하지 못했습니다. \(error.localizedDescription)") }
    }

    func fail(_ message:String) {
        let alert=NSAlert();alert.messageText="Paneloom";alert.informativeText=message
        alert.addButton(withTitle:"확인");alert.runModal()
    }

    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=navigationAction.request.url else {decisionHandler(.cancel);return}
        if let endpoint=endpoint,url.host==endpoint.host,url.port==endpoint.port {decisionHandler(.allow);return}
        if navigationAction.navigationType == .linkActivated, ["https","http"].contains(url.scheme ?? "") {NSWorkspace.shared.open(url)}
        decisionHandler(.cancel)
    }

    func webView(_ webView:WKWebView,runOpenPanelWith parameters:WKOpenPanelParameters,initiatedByFrame frame:WKFrameInfo,completionHandler:@escaping([URL]?)->Void) {
        let panel=NSOpenPanel();panel.allowsMultipleSelection=false;panel.canChooseDirectories=false
        panel.beginSheetModal(for:window){reply in completionHandler(reply == .OK ? panel.urls : nil)}
    }

    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage) {
        guard message.frameInfo.isMainFrame,let endpoint=endpoint,message.frameInfo.securityOrigin.host==endpoint.host,message.frameInfo.securityOrigin.port==endpoint.port,let data=message.body as? [String:Any],let kind=data["kind"] as? String else {return}
        if kind=="quitReady" && waitingToQuit {NSApp.reply(toApplicationShouldTerminate:true);return}
        if kind=="quitFailed" && waitingToQuit {waitingToQuit=false;NSApp.reply(toApplicationShouldTerminate:false);fail("문서를 저장하지 못했습니다. 연결 상태를 확인한 뒤 다시 종료하세요.");return}
        if kind=="openHome" {
            let home=ProcessInfo.processInfo.environment["PERSONA_LAB_HOME"].map{URL(fileURLWithPath:$0,isDirectory:true)} ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Persona Lab")
            NSWorkspace.shared.open(home);return
        }
        if kind=="export",let name=data["filename"] as? String,let body=data["body"] as? String {
            guard !exportInProgress else { fail("보고서를 저장하고 있습니다. 저장이 끝난 뒤 다시 시도하세요."); return }
            exportInProgress = true
            let isPDF = data["format"] as? String == "pdf"
            let panel=NSSavePanel();panel.nameFieldStringValue=name
            if isPDF { panel.allowedContentTypes = [.pdf] }
            panel.beginSheetModal(for:window){reply in
                guard reply == .OK,let url=panel.url else { self.exportInProgress = false; return }
                if isPDF {
                    self.pdfExporter = NativePDFExporter(html: body, destination: url) { error in
                        self.pdfExporter = nil
                        self.exportInProgress = false
                        if let error = error { self.fail("보고서를 저장하지 못했습니다. \(error.localizedDescription)") }
                    }
                } else {
                    defer { self.exportInProgress = false }
                    do { try body.write(to:url,atomically:true,encoding:.utf8) }
                    catch { self.fail("보고서를 저장하지 못했습니다. \(error.localizedDescription)") }
                }
            }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard sender === window else { return true }
        // Keep the editor open until the existing save-and-quit handshake succeeds.
        NSApp.terminate(sender)
        return false
    }

    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        if waitingToQuit{return .terminateCancel}
        guard endpoint != nil else {waitingToQuit=true;return .terminateNow}
        waitingToQuit=true
        webView.evaluateJavaScript("(() => {if(window.appCommands){window.appCommands.prepareQuit();return 'scheduled'}return 'unready'})()") { result,error in
            if error != nil || (result as? String) != "scheduled" {NSApp.reply(toApplicationShouldTerminate:true)}
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ notification:Notification) {
        waitingToQuit=true
        if let process=worker,process.isRunning {process.terminate();process.waitUntilExit()}
        try? serverLog?.close()
    }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows flag:Bool)->Bool {window.makeKeyAndOrderFront(nil);return true}
}

#if NATIVE_PDF_PROBE
NativePDFProbe.main()
#elseif NATIVE_LIFECYCLE_PROBE
NativeLifecycleProbe.main()
#else
let application=NSApplication.shared
let delegate=AppDelegate()
application.delegate=delegate
application.setActivationPolicy(.regular)
application.run()
#endif
