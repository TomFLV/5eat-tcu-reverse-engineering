# Bundled hardware drivers

The installer (`installer.iss`) installs these during setup (elevated). Fetch/refresh
them with **`fetch_drivers.ps1`** (downloads from official sources, verifies each by
Authenticode publisher and/or SHA256).

## Status

| Driver | File | Source / trust | Bundled |
|--------|------|----------------|---------|
| Edge WebView2 (app window, Win10) | `webview2\MicrosoftEdgeWebview2Setup.exe` | Microsoft, Authenticode **Valid** | ✅ staged |
| CANtact Pro WinUSB (CAN) | `canable\zadig.exe` (Zadig 2.9) | Akeo Consulting, Authenticode **Valid** | ✅ staged |
| Tactrix / FTDI serial (K-line) | `ftdi\ftdi_setup.exe` | FTDI, SHA256-pinned | ⚠️ fetch on a normal network |

FTDI's CDN returns HTTP 403 to some datacenter/VPN IPs, so it may not download in
every environment — run `fetch_drivers.ps1` from a plain connection. The URL and
SHA256 (`10C399AC…9FB1`, from the moderated Chocolatey `ftdi-drivers` package) are
pinned in the script, so the fetch is integrity-verified wherever it runs.

## What each does

- **CANtact Pro → Zadig.** gs_usb devices need **WinUSB** bound to them. Zadig (which
  embeds libwdi) is the official signed tool. The installer opens it and prompts you
  to: Options → List All Devices → select the CANtact Pro → **WinUSB** → Install.
  *(There is no official prebuilt `wdi-simple.exe` for a fully silent install; Zadig
  is the supported route. A silent install would require compiling `wdi-simple` or
  shipping a code-signed WinUSB `.inf`/`.cat` — see signing note below.)*
  Verify the CANtact's VID/PID in Device Manager (commonly `1D50:606F`).
- **Tactrix OpenPort 2.0 → FTDI CDM.** The OP2.0 enumerates via FTDI for serial SSM.
  Interactive wizard. Windows 10/11 also auto-installs an in-box FTDI driver, so on a
  normal online bench PC this may already be handled. *(If your OP2.0 needs Tactrix's
  proprietary driver/J2534 instead, bundle that installer here — confirm at bench.)*
- **WebView2** — only needed for the embedded `--shell webview` window on Windows 10;
  Windows 11 ships it. The default `--shell window` uses Edge `--app`, no runtime needed.

## Signing reality

- WebView2 and FTDI payloads are vendor-signed → silent/clean.
- The **CANtact WinUSB bind is not WHQL-signed** (Zadig/libwdi), so Windows may show a
  one-time confirmation. Fully silent everywhere needs a **code-signed WinUSB package**
  (EV/attestation cert). With a cert we can pre-build and swap that in.
- `TCUSimulator.exe` and the installer are unsigned unless signed → SmartScreen may
  warn on first run. Signing the installer removes that.
