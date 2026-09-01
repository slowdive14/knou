"""[ui_theme] 생성 HTML 페이지의 공통 디자인 — 학습현황·강의퀴즈가 같은 언어를 쓴다.

크림 페이퍼 바탕 · 잉크 활자 · 민트(완료)/애프리콧(진행중)/로즈(오답) 액센트.
색·글꼴·아이콘·버튼·화면밝기 전환을 여기 한 곳에 두고 두 페이지가 가져다 쓴다.

  - page_head(title, css)  : <!DOCTYPE>…<body> (토큰+기본 CSS+페이지별 CSS 포함)
  - SPRITE                 : 인라인 SVG 아이콘 모음(이모지 대신)
  - icon(name) / theme_button() : 아이콘·화면밝기 버튼 조각
  - page_tail(js)          : 공통 JS(테마 전환) + 페이지별 JS + </html>

⚠️ 외부 리소스 0 — 글꼴은 로컬 스택, 아이콘은 문서 안 SVG(xmlns 없이 인라인).
⚠️ 다크는 시스템 설정을 따르되, 사용자가 버튼으로 고르면 그 선택이 이긴다.
"""
from __future__ import annotations

import html as _html

# 사용자가 고른 화면 밝기를 담는 브라우저 저장 키(두 페이지가 공유 → 한 번 고르면 둘 다)
THEME_KEY = "knou_page_theme"


def esc(s) -> str:
    return _html.escape("" if s is None else str(s))


def escattr(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def icon(name: str, cls: str = "ico") -> str:
    """스프라이트 아이콘 1개(<use> 로 문서 내부 symbol 참조 — 외부 파일 아님)."""
    return f'<svg class="{cls}" viewBox="0 0 24 24"><use href="#{name}"/></svg>'


def link(url, text, cls="chip", title="", icon_name="") -> str:
    t = f' title="{escattr(title)}"' if title else ""
    body = (icon(icon_name) if icon_name else "") + f"<span>{esc(text)}</span>"
    return f'<a class="{cls}" href="{escattr(url)}"{t}>{body}</a>'


def theme_button() -> str:
    """화면 밝기 순환 버튼(시스템 → 밝게 → 어둡게)."""
    return ('<button type="button" class="chip theme" id="themeBtn" '
            'title="화면 밝기 — 시스템 / 밝게 / 어둡게">'
            '<svg class="ico" viewBox="0 0 24 24"><use href="#i-auto" id="themeIco"/>'
            '</svg><span id="themeLbl">시스템</span></button>')


def page_head(title: str, css: str = "") -> str:
    """문서 시작부 — 공통 토큰/기본 CSS + 페이지별 CSS + 깜빡임 방지 스크립트."""
    return ('<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<title>{esc(title)}</title>\n'
            '<style>\n' + CSS + "\n" + css + '\n</style>\n'
            '<script>' + BOOT_JS + '</script>\n</head>\n<body>\n' + SPRITE)


def page_tail(js: str = "") -> str:
    """문서 끝부분 — 공통 JS(테마) + 페이지별 JS."""
    return '<script>\n' + THEME_JS + "\n" + js + '\n</script>\n</body>\n</html>\n'


# ---------------------------------------------------------------------------
# 인라인 SVG 스프라이트 (HTML 안의 <svg> 는 xmlns 없이도 SVG 로 해석된다)
# ---------------------------------------------------------------------------
SPRITE = (
    '<svg class="sprite"><defs>'
    '<symbol id="i-check" viewBox="0 0 24 24">'
    '<path d="M5 12.5l4.6 4.5L19 7.5"/></symbol>'
    '<symbol id="i-x" viewBox="0 0 24 24">'
    '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></symbol>'
    '<symbol id="i-note" viewBox="0 0 24 24">'
    '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4"/>'
    '<path d="M9.5 12.5h5M9.5 16h5"/></symbol>'
    '<symbol id="i-audio" viewBox="0 0 24 24">'
    '<path d="M4 10.5v3M8 7.5v9M12 4.5v15M16 8.5v7M20 11v2"/></symbol>'
    '<symbol id="i-doc" viewBox="0 0 24 24">'
    '<path d="M3.5 4.5h17v11h-17z"/><path d="M12 15.5v4M8 19.5h8"/>'
    '<path d="M7.5 8.5h6"/></symbol>'
    '<symbol id="i-quiz" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="8.5"/>'
    '<path d="M9.6 9.6a2.4 2.4 0 1 1 2.9 2.35V14"/>'
    '<path d="M12.5 17.2h-.01"/></symbol>'
    '<symbol id="i-eye" viewBox="0 0 24 24">'
    '<path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z"/>'
    '<circle cx="12" cy="12" r="3.1"/></symbol>'
    '<symbol id="i-back" viewBox="0 0 24 24">'
    '<path d="M14.5 5.5L8 12l6.5 6.5"/></symbol>'
    '<symbol id="i-next" viewBox="0 0 24 24">'
    '<path d="M9.5 5.5L16 12l-6.5 6.5"/></symbol>'
    '<symbol id="i-reset" viewBox="0 0 24 24">'
    '<path d="M4.5 12a7.5 7.5 0 1 0 2.3-5.4"/><path d="M4.2 4.6v4.2h4.2"/></symbol>'
    '<symbol id="i-sun" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="4.2"/>'
    '<path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5'
    'M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6M18.7 18.7l-1.6-1.6M6.9 6.9L5.3 5.3"/>'
    '</symbol>'
    '<symbol id="i-moon" viewBox="0 0 24 24">'
    '<path d="M20 14.2A8.2 8.2 0 0 1 9.8 4a8.4 8.4 0 1 0 10.2 10.2z"/></symbol>'
    '<symbol id="i-auto" viewBox="0 0 24 24">'
    '<circle cx="12" cy="12" r="8.6"/>'
    '<path d="M12 3.4v17.2a8.6 8.6 0 0 0 0-17.2z" fill="currentColor" '
    'stroke="none"/></symbol>'
    '</defs></svg>'
)


# ---------------------------------------------------------------------------
# 색 토큰 — 밝은 팔레트 1벌 + 어두운 팔레트 1벌(두 셀렉터에 재사용)
# ---------------------------------------------------------------------------
_LIGHT_TOKENS = """
  --paper:#faf7f1; --paper2:#f2eee4; --card:#fff; --line:#e8e1d4;
  --ink:#15181b; --ink2:#454b52; --mute:#8b9198;
  --mint:#00a37a; --mint-s:#e3f6ef; --apri:#d98324; --apri-s:#fbf0df;
  --rose:#c8452f; --rose-s:#fbe9e5;
  --track:rgba(21,24,27,.09); --faint:rgba(21,24,27,.3);
  --shadow:0 1px 2px rgba(23,20,14,.05), 0 10px 26px -14px rgba(23,20,14,.22);
  --sans:"Pretendard Variable",Pretendard,"Apple SD Gothic Neo","Noto Sans KR","맑은 고딕","Malgun Gothic",sans-serif;
  --mono:"Cascadia Mono","Cascadia Code",Consolas,"D2Coding",ui-monospace,monospace;
  --r:14px;
"""

_DARK_TOKENS = """
  --paper:#101315; --paper2:#1b2023; --card:#171b1e; --line:#272d32;
  --ink:#eef2f4; --ink2:#b4bdc4; --mute:#7b858d;
  --mint:#2fd39f; --mint-s:#12302a; --apri:#f0ad55; --apri-s:#33260f;
  --rose:#f08a72; --rose-s:#35201b;
  --track:rgba(238,242,244,.14); --faint:rgba(238,242,244,.3);
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 12px 28px -16px rgba(0,0,0,.8);
"""

# ① 시스템이 다크이고 사용자가 '밝게'를 고르지 않았을 때 ② 직접 '어둡게'를 골랐을 때
_THEME_CSS = (
    ":root {" + _LIGHT_TOKENS + "}\n"
    '@media (prefers-color-scheme: dark) {'
    '  :root:not([data-theme="light"]) {' + _DARK_TOKENS + "  }\n}\n"
    ':root[data-theme="dark"] {' + _DARK_TOKENS + "}\n"
)


_BASE_CSS = r"""
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body {
  margin:0; padding:0 0 56px; color:var(--ink); font-family:var(--sans);
  font-size:15px; line-height:1.5; letter-spacing:-.01em;
  background:
    radial-gradient(120% 75% at 100% -10%, rgba(0,163,122,.13) 0%, transparent 55%),
    radial-gradient(90% 55% at -10% 0%, rgba(217,131,36,.11) 0%, transparent 48%),
    var(--paper);
  background-attachment:fixed;
}
.sprite { display:none; }
.wrap { max-width:1180px; margin:0 auto; padding:0 28px; }
svg.ico { width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.7;
  stroke-linecap:round; stroke-linejoin:round; flex:0 0 auto; }
svg.ico.sm { width:13px; height:13px; stroke-width:2.2; }

/* 머리말 */
.hero { padding:52px 0 28px; }
.eyebrow { margin:0; font-family:var(--mono); font-size:12px; letter-spacing:.15em;
  text-transform:uppercase; color:var(--mute); }
h1 { margin:8px 0 0; font-size:clamp(30px,4.6vw,46px); font-weight:800;
  letter-spacing:-.038em; line-height:1.04; }
.metrics { display:flex; gap:34px; flex-wrap:wrap; margin:26px 0 22px; }
.metric { min-width:148px; }
.m-lab { display:block; font-size:12px; font-weight:700; color:var(--mute); }
.m-num { display:block; font-family:var(--mono); font-size:30px; font-weight:700;
  letter-spacing:-.035em; font-variant-numeric:tabular-nums; margin-top:1px; }
.m-num em { font-style:normal; font-size:15px; color:var(--mute); font-weight:400; }
.m-rail { display:block; height:4px; border-radius:99px; margin-top:9px;
  background:var(--track); overflow:hidden; }
.m-rail i { display:block; height:100%; width:var(--w); border-radius:99px;
  background:linear-gradient(90deg,var(--mint),var(--apri));
  animation:grow .9s cubic-bezier(.2,.8,.2,1) both; }
@keyframes grow { from { width:0; } }
.tools { display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
.when { font-size:12px; color:var(--mute); display:flex; flex-direction:column;
  font-family:var(--mono); line-height:1.35; }
.when em { font-style:normal; font-family:var(--sans); opacity:.8; }

/* 알약(상태) · 칩(파일·동작) */
.pill { display:inline-flex; align-items:center; gap:5px; font-size:12px;
  font-weight:700; padding:4px 10px 4px 8px; border-radius:99px;
  border:1px solid transparent; letter-spacing:-.012em; }
.pill.ok { background:var(--mint-s); color:var(--mint); border-color:rgba(0,163,122,.22); }
.pill.fresh { color:var(--mint); border-color:rgba(0,163,122,.38); }
.pill.wait { background:var(--apri-s); color:var(--apri); border-color:rgba(217,131,36,.26); }
/* '없음' — 확인할 게 없는 정상 상태라 경고색(apri)을 쓰지 않는다 */
.pill.none { color:var(--muted); border-color:var(--line); opacity:.85; }
.pill sup { font-size:9px; margin-left:-1px; }
.pill .dot { width:6px; height:6px; border-radius:50%; background:currentColor;
  flex:0 0 auto; }
.chip { display:inline-flex; align-items:center; gap:6px; font-size:12px;
  font-weight:600; padding:5px 10px; border-radius:9px; text-decoration:none;
  color:var(--ink2); border:1px solid var(--line); background:var(--card);
  transition:transform .12s ease, border-color .12s ease, color .12s ease,
    background .12s ease; margin-right:5px; }
.chip:hover { color:var(--mint); border-color:rgba(0,163,122,.45);
  background:var(--mint-s); transform:translateY(-1px); }
.chip.ghost { color:var(--apri); border-style:dashed; border-color:rgba(217,131,36,.42);
  background:transparent; }
.chip.quiz { color:var(--mint); border-color:rgba(0,163,122,.3); background:var(--mint-s); }
.chip.cta { background:var(--ink); color:var(--paper); border-color:var(--ink);
  padding:8px 14px; border-radius:10px; font-size:13px; }
.chip.cta:hover { background:var(--mint); border-color:var(--mint); color:#fff; }
button.chip { font:inherit; cursor:pointer; }
.chip.theme { padding:7px 12px; }
.none { color:var(--faint); font-size:17px; padding-left:7px; }

/* 토글 스위치 */
.toggle { display:inline-flex; align-items:center; gap:8px; font-size:13px;
  font-weight:600; color:var(--ink2); cursor:pointer; user-select:none; }
.toggle input { position:absolute; width:1px; height:1px; opacity:0;
  clip-path:inset(50%); overflow:hidden; }
.tg { width:36px; height:20px; border-radius:99px; background:var(--line);
  position:relative; transition:background .18s ease; flex:0 0 auto; }
.tg::after { content:""; position:absolute; top:2px; left:2px; width:16px; height:16px;
  border-radius:50%; background:var(--card); box-shadow:0 1px 3px rgba(0,0,0,.28);
  transition:transform .18s cubic-bezier(.3,.8,.3,1); }
.toggle input:checked + .tg { background:var(--mint); }
.toggle input:checked + .tg::after { transform:translateX(16px); }
.toggle input:focus-visible + .tg { outline:2px solid var(--mint); outline-offset:2px; }

/* 카드 · 꼬리말 · 빈 상태 */
.card { background:var(--card); border:1px solid var(--line); border-radius:var(--r);
  box-shadow:var(--shadow); }
.legend { display:flex; align-items:center; gap:9px; flex-wrap:wrap; margin-top:20px;
  font-size:12px; color:var(--mute); }
.legend .pill.sm { font-size:11px; padding:3px 9px; font-weight:600; }
.lg-tip { margin-left:auto; font-family:var(--mono); }
.empty { background:var(--card); border:1px solid var(--line); border-radius:var(--r);
  padding:44px; display:flex; flex-direction:column; gap:6px; box-shadow:var(--shadow); }
.empty b { font-size:17px; }
.empty span { color:var(--mute); font-size:13px; }

@media (max-width:820px) {
  .wrap { padding:0 16px; }
  .hero { padding:30px 0 18px; }
  .metrics { gap:20px; }
  .metric { min-width:110px; }
  .m-num { font-size:25px; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation:none !important; transition:none !important; }
}
"""

CSS = _THEME_CSS + _BASE_CSS


# ---------------------------------------------------------------------------
# 공통 JS — 화면 밝기 전환(선택은 브라우저에 저장, 두 페이지가 같은 키를 쓴다)
# ---------------------------------------------------------------------------
BOOT_JS = """
try {
  var t = localStorage.getItem('%s');
  if (t === 'light' || t === 'dark') {
    document.documentElement.setAttribute('data-theme', t);
  }
} catch (e) {}
""" % THEME_KEY

THEME_JS = """
(function () {
  var KEY = '%s';
  var ORDER = ['auto', 'light', 'dark'];
  var LABEL = { auto: '시스템', light: '밝게', dark: '어둡게' };
  var ICON = { auto: '#i-auto', light: '#i-sun', dark: '#i-moon' };
  var btn = document.getElementById('themeBtn');
  var lbl = document.getElementById('themeLbl');
  var ico = document.getElementById('themeIco');
  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return (v === 'light' || v === 'dark') ? v : 'auto';
    } catch (e) { return 'auto'; }
  }
  function apply(v) {
    var root = document.documentElement;
    if (v === 'auto') { root.removeAttribute('data-theme'); }
    else { root.setAttribute('data-theme', v); }
    if (lbl) { lbl.innerHTML = LABEL[v]; }
    if (ico) { ico.setAttribute('href', ICON[v]); }
  }
  if (!btn) return;
  var cur = read();
  apply(cur);
  btn.onclick = function () {
    cur = ORDER[(ORDER.indexOf(cur) + 1) %% ORDER.length];
    try { localStorage.setItem(KEY, cur); } catch (e) {}
    apply(cur);
  };
})();
""" % THEME_KEY
