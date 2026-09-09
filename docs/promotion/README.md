# Promotion

## v0.3.0 update

Published on 2026-09-09: [v0.3.0 beta](https://github.com/zeusu-sato/codex-usage-tray/releases/tag/v0.3.0), with Codex + Claude support. The [Windows CI](https://github.com/zeusu-sato/codex-usage-tray/actions/runs/34332018299) passed 114 backend tests, both native UI suites, and packaged-runtime tests. Anonymous downloads of the release ZIP, checksum file, and tagged demo matched the verified build. The release targets `06a770efe86ed09f051426320bde9db76a85e10c`.

| Platform | v0.3.0 result | Verification |
| --- | --- | --- |
| [LinkedIn](https://www.linkedin.com/feed/update/urn:li:activity:7503340545587589120/) | Existing bilingual post updated | Reloaded full text matches the prepared copy after whitespace and URL shortening. Anonymous HTML exposes the new heading and preview. The original v0.2.0 attachment remains; the text explains this and links to the new demo. |
| [Reddit](https://www.reddit.com/r/ChatGPTCoding/comments/1w9lsay/comment/p8p56be/) | Existing weekly-thread comment edited | Reloaded signed-in comment shows both languages, Claude limitations, and the new release/demo links. No duplicate comment was posted. Independent anonymous visibility was not rechecked. |
| [Qiita](https://qiita.com/DoroDango/items/435ec033e0382c0ec52a) | Existing article title, body, tags, and demo updated | Reloaded article checked; anonymous HTTP 200 exposes the revised body. The new image URL and alt text are present, and the Qiita image proxy returns a PNG. Automatic X sharing and stock-user change notifications were off. |
| X | Revised copy and image prepared; still unpublished | The composer/media editor remained blank after reload, so browser draft persistence is unverified. The exact text, image, and alt text are preserved in this directory. No new posting attempt was made. |

The revised posts describe Claude support as experimental and limited to Claude Code 2.1.263. LinkedIn, Reddit, and Qiita distinguish routine monitoring without inference from a user-requested AI review that consumes Codex allowance. [published.json](published.json) records the current revision and preserves the original publication evidence below.

## v0.2.0 publication history

Status on 2026-09-09: **LinkedIn, Reddit, and Qiita posted; the user confirmed X was not posted.** The user selected the platforms and opened the previously used publication browser. Posting accounts were verified in that browser.

| Platform | Result | Verification |
| --- | --- | --- |
| [LinkedIn](https://www.linkedin.com/feed/update/urn:li:activity:7503340545587589120/) | Published as Zeusu Sato, audience Anyone, English/Japanese text and one demo image | Signed-in post and unauthenticated public page checked. |
| [Reddit](https://www.reddit.com/r/ChatGPTCoding/comments/1w9lsay/weekly_self_promotion_thread/p8p56be/) | Published as Competitive-Carob373 in the active weekly promotion thread | Signed-in comment JSON matches the prepared Markdown. Unauthenticated verification was blocked by a network policy; this does not establish removal or public visibility. |
| X | Not published, as confirmed by the user after the send error | The original attempt and profile reload failed. The user subsequently confirmed there was no post; no further attempt was made. |
| [Qiita](https://qiita.com/DoroDango/items/435ec033e0382c0ec52a) | Published as DoroDango, public audience, Japanese technical article with an English overview | Saved draft matched the source title, body, and four tags. Signed-in article, rendered code blocks, tables, and demo image checked. All nine linked resources returned HTTP 200; the demo hash matched. Independent anonymous article verification remains incomplete: direct page/API connections reset before HTTP responses and public web fetch was unavailable. |

- X: [short bilingual text](x.txt), with [demo image](../images/demo.png) and [alt text](alt.txt).
- LinkedIn: [bilingual text](linkedin.txt), the same image and alt text, public audience.
- Reddit: [bilingual comment](reddit.md), posted to the [active weekly thread](https://www.reddit.com/r/ChatGPTCoding/comments/1w9lsay/weekly_self_promotion_thread/) after confirming its pinned, unlocked, unarchived status. The comment includes project context and an AI-assistance disclosure.
- Qiita: [article source](qiita.md), covering metadata-only polling, bounded forecast history, rounding allowances, and the opaque Windows Forms toggle. The front matter records the title and tags and is excluded from the published body. The article includes an AI-assistance disclosure; automatic X sharing was disabled.

The demo image contains synthetic quota values and a visible demo label. The public source and Windows release links have been checked. Personal quota screenshots, instructions, login data, and reports must not be attached.

Rules checked:

- [X character counting](https://docs.x.com/fundamentals/counting-characters): URLs count as 23, Japanese characters generally as two; verify the final composer fits.
- [r/ChatGPTCoding rules](https://www.reddit.com/r/ChatGPTCoding/about/rules.json): promotional content, including FOSS, belongs in the weekly self-promotion thread.
- [Reddit AI disclosure guidance](https://support.reddithelp.com/hc/en-us/articles/41180423371156-Manipulated-Content-and-Misleading-Behavior).
- [Qiita community guideline](https://help.qiita.com/ja/articles/qiita-community-guideline): provide reusable technical knowledge about the software and verify AI-assisted content.

Qiita's technical claims were checked against the v0.2.0 source and the [official app-server documentation](https://learn.chatgpt.com/docs/app-server). The existing 17 forecast tests passed, and the three illustrative forecast cases were also executed against the pure calculation module. These checks do not start AI inference or access an account.

Prepared copy is preserved here for comparison with the submitted posts. X's prepared copy must not be treated as a published post.
