"""Render a newsletter dict to email-safe HTML and a plaintext fallback.

Email HTML is its own dialect: single column, table-based layout, inline
styles only (no <style> blocks or external CSS — many clients strip them),
~600px max width, and web-safe fonts. This keeps to that discipline so the
issue renders consistently in Gmail, Apple Mail, Outlook, etc.
"""

from __future__ import annotations

from html import escape

BG = "#0b0d12"
CARD = "#13161d"
TEXT = "#e8e8ea"
DIM = "#9aa0aa"
ACCENT = "#f59e0b"
COOL = "#22d3ee"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def _story_html(i: int, s: dict) -> str:
    tags = []
    if s.get("is_vendor_announcement"):
        tags.append(f'<span style="color:{ACCENT};font-weight:600">● announcement</span>')
    if s.get("source_count", 1) >= 3:
        tags.append(f'<span style="color:{DIM}">{s["source_count"]} outlets</span>')
    tag_html = (' &nbsp;·&nbsp; ' + ' &nbsp; '.join(tags)) if tags else ""
    summary = escape(s.get("summary", ""))
    headline = escape(s["headline"])
    source = escape(s.get("source", ""))
    url = escape(s["url"], quote=True)
    return f"""
        <tr><td style="padding:18px 0;border-bottom:1px solid #23262e;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
            <td valign="top" width="34" style="color:{ACCENT};font-weight:700;font-size:15px;font-family:{FONT};">{i:02d}</td>
            <td valign="top" style="font-family:{FONT};">
              <a href="{url}" style="color:{TEXT};font-size:18px;font-weight:700;text-decoration:none;line-height:1.3;">{headline}</a>
              <div style="margin-top:5px;font-size:12px;color:{DIM};">{source}{tag_html}</div>
              <div style="margin-top:8px;font-size:14px;color:{DIM};line-height:1.5;">{summary}</div>
            </td>
          </tr></table>
        </td></tr>"""


def render_html(nl: dict) -> str:
    rows = "".join(_story_html(i, s) for i, s in enumerate(nl["stories"], 1))
    intro = escape(nl.get("intro", "")).replace("\n", "<br>")
    intro_block = (
        f'<tr><td style="padding:8px 0 20px;font-family:{FONT};font-size:15px;'
        f'color:{TEXT};line-height:1.6;">{intro}</td></tr>' if intro else ""
    )
    video_block = ""
    if nl.get("video_url"):
        video_block = f"""
        <tr><td style="padding:6px 0 22px;">
          <a href="{escape(nl['video_url'], quote=True)}"
             style="display:inline-block;background:{ACCENT};color:{BG};font-family:{FONT};
             font-weight:700;font-size:15px;text-decoration:none;padding:12px 24px;border-radius:8px;">
             ▶ Watch today's 5-minute episode</a>
        </td></tr>"""

    site = escape(nl.get("site_url", ""), quote=True)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(nl['subject'])}</title></head>
<body style="margin:0;padding:0;background:{BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};">
<tr><td align="center" style="padding:28px 16px;">
  <table role="presentation" width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;width:100%;background:{CARD};border-radius:12px;padding:32px;">
    <tr><td style="font-family:{FONT};">
      <div style="color:{ACCENT};font-size:12px;letter-spacing:3px;font-weight:700;">THE DAILY PROMPT</div>
      <div style="color:{DIM};font-size:12px;margin-top:4px;">{escape(nl['issue_date'])} · AI news that actually matters</div>
    </td></tr>
    {intro_block}
    {video_block}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
    <tr><td style="padding:26px 0 0;font-family:{FONT};font-size:12px;color:{DIM};line-height:1.6;">
      You're getting this because you asked to. <a href="{site}" style="color:{COOL};">{site}</a><br>
      To stop, reply with “unsubscribe”.
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def render_text(nl: dict) -> str:
    lines = [f"THE DAILY PROMPT — {nl['issue_date']}", ""]
    if nl.get("intro"):
        lines += [nl["intro"], ""]
    if nl.get("video_url"):
        lines += [f"Watch today's episode: {nl['video_url']}", ""]
    for i, s in enumerate(nl["stories"], 1):
        lines.append(f"{i:02d}. {s['headline']} ({s.get('source','')})")
        if s.get("summary"):
            lines.append(f"    {s['summary']}")
        lines.append(f"    {s['url']}")
        lines.append("")
    lines += ["—", "Reply 'unsubscribe' to stop.", nl.get("site_url", "")]
    return "\n".join(lines)
