# Promotion

## v0.3.0 update

The platform copy and demo have been revised for Codex + Claude support. Publication updates are being verified separately; the v0.2.0 records below are historical evidence and do not establish that the revised text is already live. X remains an unpublished draft unless a new permalink is recorded.

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
