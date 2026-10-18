import AppKit
import CryptoKit
import Foundation

// Standalone bootstrap installer: no embedded SyncLab runtime or pinned version.
let repository = "contentriumkorea/synclab"
#if arch(arm64)
let packageName = "SyncLab-macOS-arm64.zip"
#else
let packageName = "SyncLab-macOS-x64.zip"
#endif

struct Asset: Decodable { let name: String; let size: Int64; let digest: String?; let browser_download_url: String }
struct Release: Decodable { let tag_name: String; let draft: Bool; let prerelease: Bool; let assets: [Asset] }
enum InstallError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text)=self {return text}; return nil }
}
func require(_ condition: Bool,_ text: String) throws { if !condition {throw InstallError.message(text)} }
@discardableResult func run(_ executable: String,_ args: [String],environment: [String:String]?=nil) throws -> String {
    let p=Process();p.executableURL=URL(fileURLWithPath:executable);p.arguments=args
    if let env=environment {p.environment=env}
    let out=Pipe(),err=Pipe();p.standardOutput=out;p.standardError=err
    try p.run()
    let bytes=out.fileHandleForReading.readDataToEndOfFile()
    let errors=err.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    try require(p.terminationStatus==0,"설치 파일 검사 또는 실행 실패: "+String(decoding:errors,as:UTF8.self))
    return String(decoding:bytes,as:UTF8.self)
}
func safeVersion(_ value: String) -> Bool {
    value.range(of:"^v?[0-9]{1,6}\\.[0-9]{1,6}\\.[0-9]{1,6}$",options:.regularExpression) != nil
}
func verifiedInstall(archive: URL,digest: String,version: String,destination: URL) throws -> URL {
    let fm=FileManager.default
    try require(safeVersion(version),"버전 정보가 올바르지 않습니다.")
    let data=try Data(contentsOf:archive,options:.mappedIfSafe)
    try require(data.count>0 && data.count<=1024*1024*1024,"다운로드 파일 크기가 올바르지 않습니다.")
    let actual=SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined()
    try require(actual==digest,"파일 검증에 실패했습니다. 설치하지 않았습니다. 다시 시도하세요.")
    let names=try run("/usr/bin/unzip",["-Z1",archive.path]).split(separator:"\n").map(String.init)
    try require(!names.isEmpty && names.count<=20000,"설치 압축이 올바르지 않습니다.")
    for name in names {
        let parts=name.split(separator:"/",omittingEmptySubsequences:false)
        try require((name=="SyncLab.app/" || name.hasPrefix("SyncLab.app/")) && !name.contains("\\") &&
            !parts.contains("..") && !parts.contains(".") && !name.contains(":"),"설치 압축 경로가 안전하지 않습니다.")
    }
    let stage=fm.temporaryDirectory.appendingPathComponent("SyncLab-install-"+UUID().uuidString)
    try fm.createDirectory(at:stage,withIntermediateDirectories:true)
    defer {try? fm.removeItem(at:stage)}
    // macOS libarchive refuses writes through archive symlinks.
    try run("/usr/bin/tar",["-xf",archive.path,"-C",stage.path,"--no-same-owner"])
    let bundle=stage.appendingPathComponent("SyncLab.app")
    let children=fm.enumerator(at:bundle,includingPropertiesForKeys:[.isSymbolicLinkKey])!
    for case let child as URL in children {
        let resolved=child.resolvingSymlinksInPath().standardizedFileURL.path
        try require(resolved.hasPrefix(bundle.path+"/"),"앱 밖을 가리키는 링크가 있습니다.")
    }
    let plist=try Data(contentsOf:bundle.appendingPathComponent("Contents/Info.plist"))
    let doc=try PropertyListSerialization.propertyList(from:plist,format:nil) as! [String:Any]
    try require(doc["CFBundleIdentifier"] as? String=="com.contentrium.synclab" &&
        doc["CFBundleShortVersionString"] as? String==version,"다른 앱 또는 버전이 다운로드됐습니다.")
    try run("/usr/bin/codesign",["--verify","--deep","--strict",bundle.path])
    let health=stage.appendingPathComponent("health.json")
    var env=ProcessInfo.processInfo.environment
    env["QT_QPA_PLATFORM"]="offscreen";env["PYTHONPATH"]="";env["PYINSTALLER_RESET_ENVIRONMENT"]="1"
    try run(bundle.appendingPathComponent("Contents/MacOS/SyncLab").path,["--update-health-check",health.path],environment:env)
    let status=try JSONSerialization.jsonObject(with:Data(contentsOf:health)) as! [String:Any]
    try require(status["success"] as? Bool==true && status["version"] as? String==version,"새 앱 실행 검사에 실패했습니다.")
    try require(!NSWorkspace.shared.runningApplications.contains{$0.bundleURL?.standardizedFileURL==destination.standardizedFileURL},"SyncLab을 종료한 뒤 다시 설치해 주세요.")
    try fm.createDirectory(at:destination.deletingLastPathComponent(),withIntermediateDirectories:true)
    let pending=destination.deletingLastPathComponent().appendingPathComponent(".SyncLab-new-"+UUID().uuidString+".app")
    let backup=destination.deletingLastPathComponent().appendingPathComponent(".SyncLab-previous-"+UUID().uuidString+".app")
    defer {try? fm.removeItem(at:pending)}
    try fm.copyItem(at:bundle,to:pending)
    let hadPrevious=fm.fileExists(atPath:destination.path)
    if hadPrevious {try fm.moveItem(at:destination,to:backup)}
    do {try fm.moveItem(at:pending,to:destination)} catch {
        if hadPrevious {try? fm.moveItem(at:backup,to:destination)}
        throw error
    }
    if hadPrevious {try? fm.removeItem(at:backup)}
    return destination
}
func latestInstall(destination: URL,progress: @escaping (String)->Void) async throws -> URL {
    progress("최신 버전 확인 중…")
    let api=URL(string:"https://api.github.com/repos/\(repository)/releases/latest")!
    var request=URLRequest(url:api);request.setValue("SyncLab-Installer",forHTTPHeaderField:"User-Agent");request.timeoutInterval=30
    let (data,response)=try await URLSession.shared.data(for:request)
    try require((response as? HTTPURLResponse)?.statusCode==200,"GitHub에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도하세요.")
    let release=try JSONDecoder().decode(Release.self,from:data)
    try require(!release.draft && !release.prerelease && safeVersion(release.tag_name),"최신 정식 버전을 찾지 못했습니다.")
    guard let asset=release.assets.first(where:{$0.name==packageName}),let sha=asset.digest,
          sha.range(of:"^sha256:[0-9a-f]{64}$",options:.regularExpression) != nil else {
        throw InstallError.message("이 Mac에 맞는 정식 설치 파일 또는 검증 정보가 없습니다.")
    }
    let allowed="https://github.com/\(repository)/releases/download/\(release.tag_name)/\(packageName)"
    try require(asset.browser_download_url==allowed && asset.size>0 && asset.size<=1024*1024*1024,"다운로드 정보가 올바르지 않습니다.")
    progress("SyncLab \(release.tag_name) 다운로드 중… (\(asset.size/1024/1024) MB)")
    var downloadRequest=URLRequest(url:URL(string:allowed)!);downloadRequest.timeoutInterval=180
    let (archive,downloadResponse)=try await URLSession.shared.download(for:downloadRequest)
    defer {try? FileManager.default.removeItem(at:archive)}
    try require((downloadResponse as? HTTPURLResponse)?.statusCode==200,"다운로드 실패. 인터넷 연결을 확인하고 다시 시도하세요.")
    let size=try FileManager.default.attributesOfItem(atPath:archive.path)[.size] as! NSNumber
    try require(size.int64Value==asset.size,"파일이 모두 다운로드되지 않았습니다. 다시 시도하세요.")
    progress("다운로드 검증 · 실행 검사 · 설치 중…")
    return try verifiedInstall(archive:archive,digest:String(sha.dropFirst(7)),version:release.tag_name.replacingOccurrences(of:"v",with:""),destination:destination)
}

if CommandLine.arguments.count==6 && CommandLine.arguments[1]=="--verify-install" {
    do {
        let args=CommandLine.arguments
        let dest=URL(fileURLWithPath:args[5]).standardizedFileURL
        try require(dest.path.hasPrefix(FileManager.default.temporaryDirectory.path),"검사 경로는 임시 폴더여야 합니다.")
        _=try verifiedInstall(archive:URL(fileURLWithPath:args[2]),digest:args[3],version:args[4],destination:dest)
        print("Native installer verification passed");exit(0)
    } catch {fputs("\(error.localizedDescription)\n",stderr);exit(1)}
}

class InstallerDelegate: NSObject,NSApplicationDelegate,NSWindowDelegate {
    var window:NSWindow!
    let label=NSTextField(wrappingLabelWithString:"최신 SyncLab을 이 Mac의 사용자 응용 프로그램 폴더에 설치합니다.")
    let progress=NSProgressIndicator()
    let button=NSButton(title:"설치",target:nil,action:nil)
    var installed:URL?
    func applicationDidFinishLaunching(_ notification:Notification) {
        window=NSWindow(contentRect:NSRect(x:0,y:0,width:500,height:245),styleMask:[.titled,.closable],backing:.buffered,defer:false)
        window.title="SyncLab 설치";window.center();window.delegate=self
        let title=NSTextField(labelWithString:"SyncLab")
        title.font=NSFont.boldSystemFont(ofSize:26);title.frame=NSRect(x:28,y:182,width:440,height:35)
        label.frame=NSRect(x:28,y:86,width:440,height:80)
        progress.frame=NSRect(x:28,y:70,width:440,height:15);progress.isIndeterminate=true;progress.style = .bar
        button.frame=NSRect(x:350,y:20,width:120,height:34);button.bezelStyle = .rounded;button.target=self;button.action=#selector(start)
        for view in [title,label,progress,button] {window.contentView!.addSubview(view)}
        window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
    }
    @objc func start() {
        if let app=installed {NSWorkspace.shared.open(app);NSApp.terminate(nil);return}
        button.isEnabled=false;progress.startAnimation(nil)
        let destination=FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/SyncLab.app")
        Task {
            do {
                let app=try await latestInstall(destination:destination) {text in DispatchQueue.main.async{self.label.stringValue=text}}
                DispatchQueue.main.async {
                    self.installed=app;self.label.stringValue="설치 완료\n\(app.path)\n앱을 휴지통으로 옮기면 제거할 수 있습니다."
                    self.button.title="SyncLab 열기";self.button.isEnabled=true;self.progress.stopAnimation(nil)
                }
            } catch {DispatchQueue.main.async {
                self.label.stringValue="설치 실패\n"+error.localizedDescription
                self.button.title="다시 시도";self.button.isEnabled=true;self.progress.stopAnimation(nil)
            }}
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool {true}
}
let installerApp=NSApplication.shared
let installerDelegate=InstallerDelegate()
installerApp.setActivationPolicy(.regular);installerApp.delegate=installerDelegate;installerApp.run()
