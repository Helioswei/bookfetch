// bookfetch 翻译桥：macOS 系统翻译（Translation framework），中英双向
//
// 协议：stdin 读 JSON 对象 {"paras": ["段1", ...], "dir": "en2zh"|"zh2en"}
// → stdout 写 JSON 译文数组（单段失败对应 null）。dir 缺省 "en2zh"（兼容旧调用）。
// 异常输出 {"error": "...", "message": "中文文案"}，退出码非 0。
//
// 编译：packaging/build_translator.sh（要求 macOS 26+，installedSource init 26.0+）
import Foundation
import Translation

func errOut(_ code: String, _ msg: String) -> Never {
    let esc = msg.replacingOccurrences(of: "\"", with: "\\\"")
    print("{\"error\":\"\(code)\",\"message\":\"\(esc)\"}")
    exit(1)
}

@main
struct TranslateBridge {
    static func main() async {
        // 1. 读 stdin（JSON 对象：paras + dir）
        let data: Data
        do {
            data = try FileHandle.standardInput.readToEnd() ?? Data()
        } catch {
            errOut("read", "读取输入失败：\(error)")
        }
        guard
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let arr = obj["paras"] as? [String]
        else {
            errOut("badInput", "stdin 需为 JSON 对象 {\"paras\": [字符串数组], \"dir\": \"en2zh\"|\"zh2en\"}")
        }
        if arr.isEmpty {
            print("[]")
            return
        }
        let dir = (obj["dir"] as? String) ?? "en2zh"
        if dir != "en2zh" && dir != "zh2en" {
            errOut("badInput", "dir 仅支持 en2zh / zh2en")
        }

        // 2. 会话（方向决定 source/target；installedSource 要求源语言包已装）
        let en = Locale.Language(identifier: "en")
        let zh = Locale.Language(identifier: "zh-Hans")
        let session: TranslationSession
        if dir == "zh2en" {
            session = TranslationSession(installedSource: zh, target: en)
        } else {
            session = TranslationSession(installedSource: en, target: zh)
        }
        if await !session.isReady {
            // 有 UI 的宿主进程（.app）里 canRequestDownloads=true 时可自动触发下载
            if session.canRequestDownloads {
                do {
                    try await session.prepareTranslation()
                } catch {
                    errOut("notInstalled", "语言包准备失败：\(error)（可在系统设置 → 通用 → 语言与地区 下载翻译语言）")
                }
            } else {
                errOut("notInstalled",
                       "翻译语言包未安装：请在 bookfetch 中打开「翻译语言包准备器」完成首次安装（约 1GB），或在系统设置 → 通用 → 语言与地区 → 翻译中下载「简体中文」")
            }
        }
        if await !session.isReady {
            errOut("notInstalled", "翻译语言包仍未就绪，请稍后重试")
        }

        // 3. 逐段翻译（同会话复用；单段失败记 null 不中断）
        var out: [String?] = []
        out.reserveCapacity(arr.count)
        for s in arr {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.isEmpty {
                out.append("")
                continue
            }
            do {
                let r = try await session.translate(s)
                out.append(r.targetText)
            } catch {
                out.append(nil)
            }
        }
        let enc: Data
        do {
            enc = try JSONSerialization.data(withJSONObject: out.map { $0 as Any })
        } catch {
            errOut("encode", "输出编码失败")
        }
        print(String(data: enc, encoding: .utf8) ?? "[]")
    }
}
