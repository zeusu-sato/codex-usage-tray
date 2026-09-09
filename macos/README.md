# Codex Usage Tray for macOS

macOS 13 or later. Separate native builds are provided for **Apple Silicon (arm64)** and **Intel (x86_64)**. The UI is Japanese; quota reset labels use JST, matching the Windows edition.

1. Download the ZIP for your Mac from the GitHub release and extract it.
2. Move **Codex Usage Tray.app** to **Applications** before enabling login startup or additional instructions. Keep the app bundle intact; its Python backend is included.
3. Open the app. The first launch shows the shared window; later launches use the menu bar. Click the Codex or Claude number to open that provider. Right-click either icon for refresh and quit.
4. Install and log into your own Codex / Claude Code client. Registered VS Code and VS Code Insiders extensions and native CLI installations are detected. If there is more than one client, use **クライアントを選ぶ…**.

The beta is **ad-hoc signed, not Developer ID signed or notarized**. If macOS blocks this downloaded app, follow Apple's [instructions for opening an app from an unidentified developer](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unidentified-developer-mh40616/mac): after checking the source and download, use **System Settings → Privacy & Security → Open Anyway**. Do not disable Gatekeeper globally. This project does not include Apple signing credentials.

## Behavior

- Two menu-bar icons show reported remaining quota; faint symbols are loaded from the user's official extensions. No standalone provider logo assets are distributed. Numbers and the color outlook remain available when the local images are absent.
- Quota reads run every five minutes; local client/version checks run every fifteen minutes. Forecasts reuse small local histories. Routine checks do not start model inference.
- Claude Code **2.1.263 only** is currently supported experimentally. Global five-hour and weekly windows are included; model-specific limits and extra usage are excluded. Unverified Claude versions pause quota reads.
- Additional instructions remain OFF until separately enabled. Changed client versions stop the old instructions. There is no fixed retirement date and no promise of quota savings.
- A fresh **Yes** opens Terminal and starts the existing interactive Codex review, using the best available model and maximum supported reasoning. This consumes Codex allowance, including when reviewing Claude. No/closing the prompt keeps monitoring without AI. Terminal preserves interactive model selection when the best model cannot be determined automatically.
- **ログイン時に起動** uses macOS login-item registration. Enable it only if wanted; macOS may request confirmation in its Login Items settings. Closing the main window keeps both icons running; **終了** quits the app.

Data is stored in `~/Library/Application Support/CodexUsageTray`; Claude has its own `providers/claude` subfolder. Tokens, passwords, and raw account identifiers are not copied. Existing clients handle authentication. See [privacy documentation](../docs/PRIVACY.md).

To remove the app, turn OFF any enabled additional instructions, disable login startup, quit, and remove the app. Removing the data folder also removes local quota history and reports. If the app is moved or removed, policy guards fail closed; do not manually enable stale instructions.

## Validation and building

Both architectures are built on macOS GitHub runners. Native UI checks use synthetic data. Packaged-runtime checks compile account-free native metadata fixtures and run with no Python on PATH. They verify read-only controls, version gating, throttling, account privacy, and that unreviewed instructions cannot be enabled. Real-account Keychain access, interactive AI review, login restart, and downloaded-app Gatekeeper approval still require a user Mac; CI results do not establish those outcomes.

The package uses the hash-pinned Python.org CPython 3.13.15 macOS installer. `collect_notices.py` verifies its identity, dependency versions, and immutable Mach-O code sections before copying notices; it records relocated binary hashes. Run the commands in [.github/workflows/macos.yml](../.github/workflows/macos.yml) on a clean macOS build environment. The installer command is intended for disposable CI or an explicit developer setup, not app users.
