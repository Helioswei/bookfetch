// bookfetch 翻译语言包准备器（macOS 26.4+）
//
// 为什么需要它：macOS 的 Translation 框架只有带 UI 的 SwiftUI 翻译会话
// (translationTask) 才允许请求语言包下载/安装；CLI/普通 App 会话
// canRequestDownloads=false。bookfetch 桌面壳是 pywebview，无法创建该会话，
// 因此翻译桥首次遇 notInstalled 时拉起本准备器，由用户点一下完成
// 语言包下载+安装（系统级一次性，装完全机所有 App 共享）。
//
// 编译：packaging/build_activator.sh

import SwiftUI
import Translation

@main
struct ActivatorApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView().frame(width: 520, height: 300)
        }
    }
}

@MainActor
struct ContentView: View {
    @State private var phase: Phase = .idle
    @State private var cfg: TranslationSession.Configuration?

    enum Phase: Equatable {
        case idle, preparing, ready, failed(String)
        var text: String {
            switch self {
            case .idle: return ""
            case .preparing: return "正在准备语言包… 首次下载约 1GB，可能需几分钟"
            case .ready: return "✓ 语言包已就绪，翻译可用。现在可以关闭本窗口，回 bookfetch 再点「译」。"
            case .failed(let m): return "准备失败：\(m)"
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("bookfetch 翻译语言包准备器").font(.headline)
            Text("为「英译中」功能准备 macOS 系统翻译模型：完全离线翻译，内容不出本机。")
                .font(.callout).foregroundStyle(.secondary)
            Text("首次需要下载约 1GB 系统级翻译模型（Apple 服务器，仅一次，装完全机 App 共用）；\n也可改在 系统设置 → 通用 → 语言与地区 → 翻译 中先下载。")
                .font(.callout)
            Button {
                cfg = TranslationSession.Configuration(
                    source: Locale.Language(identifier: "en"),
                    target: Locale.Language(identifier: "zh-Hans"),
                    preferredStrategy: .highFidelity)
            } label: {
                Text(phase == .idle ? "准备英译中语言包" : "重新准备")
            }
            .disabled(phase == .preparing)
            .keyboardShortcut(.defaultAction)
            Text(phase.text)
                .font(.callout)
                .foregroundStyle(phase == .ready ? Color.green : (phase == .failed("") ? .red : .secondary))
            Spacer()
        }
        .padding(24)
        .translationTask(cfg) { session in
            phase = .preparing
            // 请求下载+安装（首次会在系统层下载，几十秒到几分钟）
            do { try await session.prepareTranslation() } catch {
                phase = .failed("\(error.localizedDescription)")
                return
            }
            var waited = 0
            while await !session.isReady && waited < 1500 {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                waited += 2
            }
            phase = await session.isReady ? .ready : .failed("等待超时，请检查网络后重试")
        }
    }
}
