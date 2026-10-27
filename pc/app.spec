# PyInstaller spec — 카톡 오픈챗 들낙 감지기 (PC카톡, 단일 exe)
# 빌드: pyinstaller app.spec --noconfirm
from PyInstaller.utils.hooks import collect_all

datas = [('dashboard.html', '.')]
binaries = []
hiddenimports = ['pc_detector']

# cryptography / pywebview 번들 보강
for pkg in ('cryptography', 'webview'):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='KakaoInoutDetector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # 창 없는 GUI 앱 (pywebview 실패 시 기본 브라우저로 폴백)
    disable_windowed_traceback=False,
    icon=None,
)
