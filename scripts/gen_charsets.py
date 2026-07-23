"""由编码枚举生成兜底字表(不依赖外部字表文件):
   CN = GB2312 全部汉字(一+二级,~6763);JP = JIS X0208 汉字 + 全假名。
   这样"改题即缺字"的风险被常用字兜住,无需维护巨型字符列表。"""
import argparse


def gb2312_hanzi():
    chars = set()
    for hi in range(0xB0, 0xF8):          # 一级 B0-D7、二级 D8-F7
        for lo in range(0xA1, 0xFF):
            try:
                ch = bytes([hi, lo]).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if '一' <= ch <= '鿿':
                chars.add(ch)
    return chars


def jis_kanji_kana():
    chars = set()
    # 假名:平假名 3040-309F、片假名 30A0-30FF、半角片假名 FF61-FF9F
    for cp in list(range(0x3041, 0x3097)) + list(range(0x30A1, 0x30FB)) + list(range(0xFF66, 0xFFA0)):
        chars.add(chr(cp))
    # JIS X0208 汉字:遍历 EUC-JP 双字节区(A1-FE, A1-FE)解码取汉字
    for hi in range(0xA1, 0xFF):
        for lo in range(0xA1, 0xFF):
            try:
                ch = bytes([hi, lo]).decode("euc_jp")
            except UnicodeDecodeError:
                continue
            if '一' <= ch <= '鿿':
                chars.add(ch)
    return chars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cn", default="scripts/charset_cn.txt")
    ap.add_argument("--jp", default="scripts/charset_jp.txt")
    a = ap.parse_args()
    open(a.cn, "w", encoding="utf-8").write("".join(sorted(gb2312_hanzi())))
    open(a.jp, "w", encoding="utf-8").write("".join(sorted(jis_kanji_kana())))
    print("cn", len(gb2312_hanzi()), "jp", len(jis_kanji_kana()))


if __name__ == "__main__":
    main()
