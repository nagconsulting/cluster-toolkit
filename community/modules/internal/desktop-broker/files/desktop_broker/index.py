# Copyright 2026 "Google LLC"
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A list of the desktops a user can reach.

Every desktop host serves the same list, so it is reachable wherever the user
lands rather than depending on one host staying up. The entries are handed down
in the broker's configuration, which Terraform builds from the load balancer's
own backend services - so the list cannot describe a desktop that was never
deployed, the way metadata left on shared storage by a since-deleted host can.

Rendered here rather than templated in Terraform: escaping a hostname into HTML
is a job for a language with an escaping function.
"""

import html

STYLE = """
  :root { color-scheme: light dark; }
  body { font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
         margin: 0; padding: 3rem 1.5rem; display: flex;
         justify-content: center; }
  main { width: 100%; max-width: 34rem; }
  h1 { font-size: 1.35rem; margin: 0 0 .35rem; }
  p.who { margin: 0 0 2rem; opacity: .7; font-size: .9rem; }
  ul { list-style: none; padding: 0; margin: 0; }
  li { margin-bottom: .6rem; }
  a.desktop { display: block; padding: .85rem 1rem; text-decoration: none;
              border: 1px solid rgba(128,128,128,.35); border-radius: 6px;
              color: inherit; }
  a.desktop:hover, a.desktop:focus-visible { border-color: currentColor; }
  a.desktop .name { font-weight: 600; }
  a.desktop .host { display: block; font-size: .85rem; opacity: .65;
                    word-break: break-all; }
  p.empty { opacity: .7; }
"""


def render(entries, email=""):
    """Build the desktop listing page.

    entries: [{"name": ..., "url": ..., "description": ...}]
    """
    items = []
    for entry in entries:
        name = html.escape(str(entry.get("name") or "").strip())
        url = str(entry.get("url") or "").strip()
        description = html.escape(str(entry.get("description") or "").strip())
        if not name or not url:
            continue
        # Only ever link somewhere a browser can follow safely: a scheme like
        # "javascript:" reaching this page would otherwise become a link.
        if not (url.startswith("https://") or url.startswith("http://")):
            continue
        safe_url = html.escape(url, quote=True)
        label = f"{name}" if not description else f"{name} - {description}"
        items.append(
            f'      <li><a class="desktop" href="{safe_url}">'
            f'<span class="name">{label}</span>'
            f'<span class="host">{html.escape(url)}</span></a></li>'
        )

    if items:
        body = "    <ul>\n" + "\n".join(items) + "\n    </ul>"
    else:
        body = '    <p class="empty">No desktops are configured.</p>'

    who = (
        f'    <p class="who">Signed in as {html.escape(email)}</p>'
        if email
        else ""
    )

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Desktops</title>\n"
        f"  <style>{STYLE}  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        "    <h1>Desktops</h1>\n"
        f"{who}\n"
        f"{body}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )
