#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
筑波大学 出退勤 かんたん打刻アプリ
- 大きな「出勤」「退勤」ボタンを押すだけで、勤怠ポータル(skinmu)に自動で打刻します。
- 初回だけブラウザで手動ログインすれば、以後はログイン状態が保存され、ボタン1つで打刻できます。
- パスワードはこのアプリには保存しません（ブラウザのログイン状態のみを再利用します）。

必要なもの: Python 3.8以上 と Playwright。導入は setup.command が自動で行います。
"""

import csv
import json
import os
import sys
import threading
from datetime import datetime

import tkinter as tk
from tkinter import scrolledtext

# ---- 保存場所の準備（Mac/Windows 両対応） ----------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))

if sys.platform == "darwin":
    DATA_DIR = os.path.expanduser("~/Library/Application Support/TsukubaKintai")
elif os.name == "nt":
    DATA_DIR = os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")), "TsukubaKintai")
else:
    DATA_DIR = os.path.expanduser("~/.tsukuba_kintai")

PROFILE_DIR = os.path.join(DATA_DIR, "browser_profile")   # ログイン状態の保存先
LOG_CSV = os.path.join(DATA_DIR, "打刻記録.csv")           # 手元の打刻控え
os.makedirs(PROFILE_DIR, exist_ok=True)

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
KEYCHAIN_SERVICE = "TsukubaKintai"   # ログイン情報の保存先の識別名
KEYCHAIN_USER_KEY = "_saved_username"  # ユーザーID自体を保存しておく鍵


# ---- ログイン情報の安全な保管（keyring: Macはキーチェーン、Windowsは資格情報マネージャー）
def keychain_get():
    """保存された (ID, パスワード) を取得。未登録なら (None, None)。"""
    try:
        import keyring
        user = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_USER_KEY)
        if not user:
            return None, None
        pw = keyring.get_password(KEYCHAIN_SERVICE, user)
        if user and pw:
            return user, pw
        return None, None
    except Exception:
        return None, None


def keychain_set(user: str, pw: str) -> bool:
    """ID・パスワードを保存（既存があれば上書き）。"""
    try:
        import keyring
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_USER_KEY, user)
        keyring.set_password(KEYCHAIN_SERVICE, user, pw)
        return True
    except Exception:
        return False


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_local_log(action: str, result: str):
    """打刻の控えを手元CSVに残す（ポータルとは別の自分用バックアップ）。"""
    new = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["日時", "操作", "結果"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, result])


# ---- ブラウザ操作（Playwright） -------------------------------------
def do_punch(action_label: str, button_text: str, cfg: dict, log):
    """
    action_label: "出勤" or "退勤"（画面表示用）
    button_text : 実際にクリックするボタンの文字
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("❌ Playwright が入っていません。先に setup.command を実行してください。")
        return

    login_url = cfg["login_url"]
    mypage_url = cfg["mypage_url"]
    confirm_text = cfg.get("confirm_button_text", "").strip()
    channel = cfg.get("browser_channel", "").strip()
    keep_open = int(cfg.get("keep_open_seconds", 5))

    log(f"▶ {action_label} 打刻を開始します…")

    with sync_playwright() as p:
        launch_kwargs = dict(user_data_dir=PROFILE_DIR, headless=False)
        if channel:
            launch_kwargs["channel"] = channel  # 例: chrome
        try:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            # Chrome が無い等の場合は付属ブラウザで再試行
            log(f"（Chrome起動に失敗したため付属ブラウザで再試行: {e}）")
            launch_kwargs.pop("channel", None)
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)

        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # JavaScriptの確認ダイアログ（OK/キャンセル）は自動でOKする
        page.on("dialog", lambda d: d.accept())

        try:
            page.goto(mypage_url, wait_until="domcontentloaded", timeout=30000)

            # ログイン画面に飛ばされたら、自動ログイン → だめなら手動ログインを待つ
            if not _ensure_login(page, log):
                _hold_and_close(ctx, keep_open, log)
                return

            log("🖱 打刻ボタンを探しています…")

            # 上級設定: config.json にCSSセレクタが指定されていればそれを最優先
            css = cfg.get(
                "clock_in_css" if action_label == "出勤" else "clock_out_css", ""
            ).strip()
            clicked = _click_by_css(page, css, log) if css else False

            if not clicked:
                clicked = _find_and_click(page, button_text, log)

            # トップ画面に無ければ、打刻ページ（出退勤管理）を開いて探す
            if not clicked:
                nav_text = cfg.get("punch_page_link_text", "出退勤管理").strip()
                if nav_text:
                    log(f"（この画面に無いため「{nav_text}」を開いて探します…）")
                    if _click_by_text(page, nav_text, log):
                        page.wait_for_load_state("domcontentloaded")
                        clicked = _find_and_click(page, button_text, log)

            if not clicked:
                log(f"⚠ 「{button_text}」ボタンが見つかりませんでした。")
                _list_buttons(page, log)
                log("   上の一覧に打刻ボタンがあれば、その文字を config.json に設定してください。")
                log("   （ブラウザは開いたままにします。手動で打刻もできます）")
                save_local_log(action_label, "失敗: ボタンが見つからない")
                _hold_and_close(ctx, keep_open + 30, log)
                return

            # 確認ボタンがあれば押す
            if confirm_text:
                _click_by_text(page, confirm_text, log)

            page.wait_for_timeout(1500)

            # 確認用スクリーンショット
            shot = os.path.join(DATA_DIR, f"最終打刻_{action_label}.png")
            try:
                page.screenshot(path=shot)
            except Exception:
                pass

            log(f"✅ {action_label} ボタンを押しました（{datetime.now().strftime('%H:%M:%S')}）。")
            log("   ブラウザ画面に打刻時刻が表示されているかご確認ください。")
            save_local_log(action_label, "ボタン押下")
            _hold_and_close(ctx, keep_open, log)

        except Exception as e:
            log(f"❌ エラー: {e}")
            save_local_log(action_label, f"失敗: {e}")
            _hold_and_close(ctx, keep_open, log)


def _ensure_login(page, log):
    """ログイン画面なら自動 or 手動でログインを済ませる。成功したら True。"""
    if "/user" not in page.url:
        return True
    logged_in = False
    user, pw = keychain_get()
    if user and pw:
        log("🔑 保存されたログイン情報で自動ログインします…")
        logged_in = _auto_login(page, user, pw, log)
        if not logged_in:
            log("⚠ 自動ログインに失敗しました。パスワードを変更した場合は")
            log("   アプリの「⚙ ログイン設定」から再登録してください。")
    if not logged_in:
        if not (user and pw):
            log("🔑 ログインが必要です。開いたブラウザでID・パスワードを入力してください。")
            log("   （「⚙ ログイン設定」に登録しておくと次回から自動になります）")
        log("   （ログインが終わり打刻画面が表示されるまで最大3分待ちます）")
        try:
            page.wait_for_url("**/mypage*", timeout=180000)
        except Exception:
            log("⌛ 時間内にログインが確認できませんでした。もう一度ボタンを押してください。")
            return False
    page.wait_for_load_state("domcontentloaded")
    return True


def _auto_login(page, user, pw, log):
    """ログイン画面にID・パスワードを自動入力して送信。成功したら True。"""
    try:
        # ID欄: 最初に見えるテキスト入力欄
        id_box = page.locator(
            "input[type='text'], input[type='email'], input:not([type])"
        ).first
        id_box.wait_for(state="visible", timeout=10000)
        id_box.fill(user)
        # パスワード欄
        pw_box = page.locator("input[type='password']").first
        pw_box.fill(pw)
    except Exception as e:
        log(f"（自動ログイン: ID/パスワードの入力でエラー: {e}）")
        return False

    # ログインボタン: 打刻ボタン探索と同じ堅牢なロジック（iframe内・複数パターン）で探す
    clicked = _click_by_text(page, "ログイン", log)
    if not clicked:
        clicked = _click_by_css(
            page, "button[type='submit'], input[type='submit']", log)
    if not clicked:
        log("（自動ログイン: ログインボタンが見つからないため、Enterキーで送信します）")
        try:
            pw_box.press("Enter")
        except Exception as e:
            log(f"（自動ログイン: Enterキー送信でもエラー: {e}）")
            return False

    try:
        page.wait_for_url("**/mypage*", timeout=20000)
        return True
    except Exception as e:
        log(f"（自動ログイン: ボタンは押しましたがマイページに移動しませんでした: {e}）")
        return False


def _find_and_click(page, text, log, attempts=4, interval_ms=1500):
    """ボタンを繰り返し探してクリック（画面の表示が遅い場合に備えて数秒粘る）。"""
    for i in range(attempts):
        if _click_by_text(page, text, log):
            return True
        page.wait_for_timeout(interval_ms)
    return False


def _click_by_text(page, text, log):
    """表示文字からボタンを探してクリック。iframe（画面内の別枠）の中も探す。"""
    found_disabled = [False]
    for frame in page.frames:
        if _click_in_frame(frame, text, log, found_disabled):
            return True
    if found_disabled[0]:
        log(f"⚠ 「{text}」ボタンはありましたが、押せない（無効）状態でした。")
    return False


def _click_in_frame(frame, text, log, found_disabled):
    """1つのフレーム内でボタンを探してクリック。
    まず本物のボタン類、最後に『文字がぴったり一致する要素』も試す
    （部分一致のただの文字（「退勤時刻」等）は絶対にクリックしない）。"""
    selectors = [
        f"button:has-text('{text}')",
        (f"input[type='button'][value*='{text}'], "
         f"input[type='submit'][value*='{text}'], "
         f"input[type='image'][alt*='{text}']"),
        f"[role='button']:has-text('{text}')",
        f"text=\"{text}\"",   # 表示文字が完全一致する要素（JS製ボタン対策）
        f"a:has-text('{text}')",
        f"[onclick]:has-text('{text}')",
    ]
    for sel in selectors:
        try:
            loc = frame.locator(sel)
            for i in range(min(loc.count(), 10)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    if not el.is_enabled():
                        found_disabled[0] = True
                        continue
                    desc = el.evaluate(
                        "e => e.tagName + '「' + (e.value || e.textContent || '').trim().slice(0, 20) + '」'"
                    )
                    el.click(timeout=5000)
                    log(f"🖱 クリックしました: {desc}")
                    return True
                except Exception:
                    continue
        except Exception:
            continue
    return False


def _click_by_css(page, css, log):
    """config.json で指定されたCSSセレクタでクリック（全フレーム対象）。
    透明・非表示スタイルのボタンでも押せるよう、通常クリックがだめなら
    JavaScript経由でクリックする。"""
    for frame in page.frames:
        try:
            el = frame.locator(css).first
            if el.count() == 0:
                continue
            try:
                el.click(timeout=4000)
            except Exception:
                el.evaluate("e => e.click()")   # 強制クリック（透明ボタン対策）
            log(f"🖱 打刻ボタンを押しました（{css}）")
            return True
        except Exception:
            continue
    return False


def _list_buttons(page, log):
    """画面上に見えているボタン類の文字を一覧表示（原因調査用）。iframe内も見る。"""
    all_texts = []
    for frame in page.frames:
        try:
            texts = frame.eval_on_selector_all(
                "button, input[type='button'], input[type='submit'], a, [role='button'], [onclick]",
                "els => els.filter(e => e.offsetParent !== null)"
                ".map(e => (e.value || e.textContent || '').trim())"
                ".filter(t => t && t.length <= 20)"
            )
            all_texts.extend(texts)
        except Exception:
            continue
    uniq = list(dict.fromkeys(all_texts))[:25]
    if uniq:
        log("📋 いま画面にあるボタン: " + " ／ ".join(uniq))


def do_diagnose(cfg, log):
    """マイページを開き、画面の中身をファイルに保存する（原因調査用）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("❌ Playwright が入っていません。先に setup.command を実行してください。")
        return

    channel = cfg.get("browser_channel", "").strip()
    log("🔍 画面調査を開始します…")
    with sync_playwright() as p:
        launch_kwargs = dict(user_data_dir=PROFILE_DIR, headless=False)
        if channel:
            launch_kwargs["channel"] = channel
        try:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception:
            launch_kwargs.pop("channel", None)
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(cfg["mypage_url"], wait_until="domcontentloaded", timeout=30000)
            if not _ensure_login(page, log):
                _hold_and_close(ctx, 3, log)
                return
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            for i, frame in enumerate(page.frames):
                try:
                    html = frame.content()
                    name = f"診断_マイページ_{i}.html" if i else "診断_マイページ.html"
                    with open(os.path.join(APP_DIR, name), "w", encoding="utf-8") as f:
                        f.write(html)
                    log(f"💾 保存: {name}")
                except Exception:
                    continue
            try:
                page.screenshot(path=os.path.join(APP_DIR, "診断_マイページ.png"),
                                full_page=True)
                log("💾 保存: 診断_マイページ.png")
            except Exception:
                pass
            log("✅ 調査ファイルをアプリのフォルダに保存しました。")
            log("   このファイルがあれば、ボタンの正確な場所を特定できます。")
            _hold_and_close(ctx, 3, log)
        except Exception as e:
            log(f"❌ エラー: {e}")
            _hold_and_close(ctx, 3, log)


def _hold_and_close(ctx, seconds, log):
    try:
        if seconds > 0:
            log(f"（{seconds}秒後にブラウザを閉じます）")
            import time
            time.sleep(seconds)
        ctx.close()
    except Exception:
        pass


def _pick_font():
    """OSごとに存在する日本語フォントを選ぶ。"""
    if sys.platform == "darwin":
        return "Hiragino Sans"
    if os.name == "nt":
        return "Yu Gothic UI"
    return "TkDefaultFont"


# ---- 画面（GUI） ----------------------------------------------------
class App:
    def __init__(self, root):
        self.cfg = load_config()
        self.busy = False
        FONT = _pick_font()
        root.title("筑波大学 出退勤 打刻")
        root.geometry("440x470")
        root.configure(bg="#f2f4f7")

        tk.Label(root, text="出退勤 かんたん打刻", font=(FONT, 20, "bold"),
                 bg="#f2f4f7", fg="#1f2d3d").pack(pady=(18, 4))
        tk.Label(root, text="ボタンを押すと自動で打刻します", font=(FONT, 12),
                 bg="#f2f4f7", fg="#5a6b7b").pack(pady=(0, 12))

        self.btn_in = tk.Button(root, text="出　勤", font=(FONT, 22, "bold"),
                                bg="#2e7d32", fg="white", activebackground="#1b5e20",
                                width=12, height=2, bd=0, highlightthickness=0,
                                command=self.on_clock_in)
        self.btn_in.pack(pady=8)

        self.btn_out = tk.Button(root, text="退　勤", font=(FONT, 22, "bold"),
                                 bg="#c62828", fg="white", activebackground="#8e0000",
                                 width=12, height=2, bd=0, highlightthickness=0,
                                 command=self.on_clock_out)
        self.btn_out.pack(pady=8)

        row = tk.Frame(root, bg="#f2f4f7")
        row.pack(pady=(2, 0))
        tk.Button(row, text="⚙ ログイン設定", font=(FONT, 11),
                  command=self.open_login_settings).pack(side="left", padx=4)
        tk.Button(row, text="🔍 画面調査", font=(FONT, 11),
                  command=self.on_diagnose).pack(side="left", padx=4)

        mono_font = "Menlo" if sys.platform == "darwin" else "Consolas"
        self.log_box = scrolledtext.ScrolledText(root, height=7, font=(mono_font, 11),
                                                 bg="#0f1720", fg="#d7e2ec", bd=0)
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(14, 14))
        user, pw = keychain_get()
        if user and pw:
            self.log(f"準備完了。自動ログイン設定済み（ID: {user}）。")
        else:
            self.log("準備完了。「⚙ ログイン設定」にID・パスワードを登録すると全自動になります。")

    def open_login_settings(self):
        FONT = _pick_font()
        store_name = "Macのキーチェーン" if sys.platform == "darwin" else "Windowsの資格情報マネージャー"
        win = tk.Toplevel()
        win.title("ログイン設定")
        win.geometry("360x220")
        win.configure(bg="#f2f4f7")
        tk.Label(win, text="統一認証のログイン情報", font=(FONT, 14, "bold"),
                 bg="#f2f4f7").pack(pady=(16, 2))
        tk.Label(win, text=f"{store_name}に保存されます（ファイルには残りません）",
                 font=(FONT, 10), bg="#f2f4f7", fg="#5a6b7b").pack()

        frm = tk.Frame(win, bg="#f2f4f7")
        frm.pack(pady=10)
        tk.Label(frm, text="ID", font=(FONT, 12), bg="#f2f4f7").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        e_user = tk.Entry(frm, width=22, font=(FONT, 12))
        e_user.grid(row=0, column=1, pady=4)
        tk.Label(frm, text="パスワード", font=(FONT, 12), bg="#f2f4f7").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        e_pw = tk.Entry(frm, width=22, font=(FONT, 12), show="●")
        e_pw.grid(row=1, column=1, pady=4)

        cur_user, _ = keychain_get()
        if cur_user:
            e_user.insert(0, cur_user)

        def save():
            u, p = e_user.get().strip(), e_pw.get()
            if not u or not p:
                self.log("⚠ IDとパスワードの両方を入力してください。")
                return
            if keychain_set(u, p):
                self.log(f"✅ ログイン情報を保存しました（ID: {u}）。次回から自動ログインします。")
            else:
                self.log("❌ 保存に失敗しました。")
            win.destroy()

        tk.Button(win, text="保存", font=(FONT, 12, "bold"),
                  command=save, width=10).pack(pady=8)

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")

    def _run(self, label, button_text):
        if self.busy:
            self.log("実行中です。少しお待ちください。")
            return
        self.busy = True
        self.btn_in.config(state="disabled")
        self.btn_out.config(state="disabled")

        def worker():
            try:
                do_punch(label, button_text, self.cfg, self._safe_log)
            finally:
                self.busy = False
                self.btn_in.config(state="normal")
                self.btn_out.config(state="normal")

        threading.Thread(target=worker, daemon=True).start()

    def _safe_log(self, msg):
        # 別スレッドからでも安全にログ表示
        self.log_box.after(0, lambda: self.log(msg))

    def on_clock_in(self):
        self._run("出勤", self.cfg["clock_in_button_text"])

    def on_clock_out(self):
        self._run("退勤", self.cfg["clock_out_button_text"])

    def on_diagnose(self):
        if self.busy:
            self.log("実行中です。少しお待ちください。")
            return
        self.busy = True
        self.btn_in.config(state="disabled")
        self.btn_out.config(state="disabled")

        def worker():
            try:
                do_diagnose(self.cfg, self._safe_log)
            finally:
                self.busy = False
                self.btn_in.config(state="normal")
                self.btn_out.config(state="normal")

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
