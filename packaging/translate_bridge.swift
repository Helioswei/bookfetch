// bookfetch 翻译桥：macOS 系统翻译（Translation framework）
//
// 协议：stdin 读 JSON 字符串数组（待译段落）→ stdout 写 JSON 数组（译文；
// 单段失败对应 null）。异常输出 {"error": "..."}，退出码非 0。
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
        // 1. 读 stdin（整段 JSON 数组）
        let data: Data
        do {
            data = try FileHandle.standardInput.readToEnd() ?? Data()
        } catch {
            errOut("read", "读取输入失败：\(error)")
        }
        guard let arr = try? JSONSerialization.jsonObject(with: data) as? [String] else {
            errOut("badInput", "stdin 需为 JSON 字符串数组")
        }
        if arr.isEmpty {
            print("[]")
            return
        }

        // 2. 会话（en → zh-Hans；installedSource 要求语言包已装）
        let en = Locale.Language(identifier: "en")
        let zh = Locale.Language(identifier: "zh-Hans")
        let session = TranslationSession(installedSource: en, target: zh)
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
                       "系统翻译语言包未安装：请先在系统设置 → 通用 → 语言与地区 → 翻译中下载简体中文，或在任意英文网页用 Safari 翻译一次触发安装")
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
