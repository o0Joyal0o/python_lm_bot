# python_lm_bot
Lords Mobile Traffic Analysis Project: Complete Master Document
Project Goal
To intercept, decrypt, and analyze network traffic between the Lords Mobile game client and its servers for the purpose of understanding its chat protocol and automating messages.

Core Technical Concepts
1. Man-in-the-Middle (MITM) Attack
What it is: Intercepting communication between two parties (game client and server).

How it works: mitmproxy acts as a proxy server, routing all traffic through your PC.

Requirement: You must install a custom Certificate Authority (CA) on the device to decrypt HTTPS.

2. HTTPS & TLS Encryption
Purpose: Encrypts data to prevent eavesdropping.

Interception Challenge: Without the mitmproxy CA certificate, traffic appears as gibberish.

Error: TLS handshake failed means the client rejected mitmproxy's certificate.

3. Certificate Pinning
What it is: A security technique where an app only trusts specific certificates (its own), ignoring user-installed ones.

Effect: Causes the "Disconnected" error in Lords Mobile even after installing the mitmproxy cert.

Solution: Patch the game's APK to remove pinning checks.

4. Root Access
Why needed: Installing a system CA certificate often requires administrator (root) privileges on Android.

Emulator Note: Most emulators disable root by default for security.

5. Network Bridging vs. Proxy
Bridging: Connects the emulator directly to your network. Doesn't force traffic through a proxy.

Proxy: Explicitly routes all network requests through a specified server (your mitmproxy).

Tool Glossary
mitmproxy
Role: HTTP/S proxy tool for intercepting traffic.

Key Flags:

-s script.py: Runs a custom Python script.

--mode transparent: Listens for all traffic without client proxy configuration.

Critical URL: http://mitm.it - provides CA certificates for installation.

ADB (Android Debug Bridge)
Purpose: Communicates with an Android device/emulator from your PC.

Key Commands:

adb devices: Lists connected devices.

adb shell: Opens a remote shell.

adb install app.apk: Installs an APK.

adb push local remote: Copies a file to the device.

adb shell settings put global http_proxy 10.0.2.2:8080: Sets a global proxy.

ProxyDroid
Type: Android app.

Function: Configures system-wide proxy settings on Android.

Requirement: Root access to work reliably.

Configuration:

Host: 10.0.2.2 (Special IP for host PC from Android emulator)

Port: 8080 (mitmproxy's default port)

Type: HTTP

WSA (Windows Subsystem for Android)
What it is: A native Android environment built into Windows 11.

Advantage: Lightweight, no Hyper-V conflicts.

Challenge: Difficult to configure for proxying; requires custom rooted builds.

Complete Error Encyclopedia & Solutions
Error 1: [0/0] Flows in mitmproxy
Meaning: No traffic is reaching mitmproxy.

Causes:

Emulator not configured to use the proxy.

Proxy settings applied incorrectly.

Solutions:

Use ProxyDroid (with root) or the emulator's network settings to set proxy to 10.0.2.2:8080.

Test by visiting http://mitm.it in the emulator's browser. If the page loads, the proxy is working.

Error 2: TLS handshake failed. The client does not trust the proxy's certificate.
Meaning: The device has not installed and trusted the mitmproxy CA certificate.

Solution:

In the emulator, visit http://mitm.it.

Download and install the Android certificate.

On Android 10+: You must also enable the certificate in Settings -> Security -> Encryption & credentials -> Trusted credentials -> USER tab.

Error 3: d certificate in mitmproxy flow list
Meaning: Decryption failed because the certificate wasn't trusted.

Solution: Same as Error 2; ensure the certificate is properly installed and enabled.

Error 4: "Disconnected. Failed to download data." in Lords Mobile
Meaning: Certificate Pinning. The game detected the MITM proxy and terminated the connection.

Solution: You must patch the Lords Mobile APK to disable certificate pinning.

Download the APK from a site like APKPure.

Use mitmproxy's certutil tool:
certutil -p "lords_mobile.apk"

Install the patched APK on your emulator.

Error 5: 'openssl' is not recognized
Meaning: OpenSSL is not installed on your Windows PC.

Solution: Not strictly necessary. Use certutil from mitmproxy instead for patching.

Error 6: Hyper-V is enabled, which may block the launch... (LDPlayer)
Meaning: Virtualization conflict between Hyper-V and VirtualBox (which LDPlayer uses).

Solution:

Disable Hyper-V and Virtual Machine Platform in "Turn Windows features on or off".

OR, switch to an emulator that uses Hyper-V natively (WSA, Windows 11 Android Studio emulator).

Error 7: PLEASE ROOT YOUR DEVICE FIRST !!! (ProxyDroid)
Meaning: The emulator does not have root access enabled.

Solution:

Create a new instance in your emulator (e.g., NoxPlayer Multi-Drive).

During creation, enable the "Root" or "Enable Root" option.

Grant root permission to ProxyDroid when prompted.

Error 8: Install.ps1 is not recognized
Meaning: You ran the command incorrectly in PowerShell.

Solution: Use .\Install.ps1 to execute the script in the current directory.

The Final, Victorious Setup Guide
Recommended Stack: NoxPlayer + ProxyDroid + Patched APK
Setup Emulator:

Install NoxPlayer.

Use the Multi-Drive manager to create a new instance. Ensure "Root" is enabled.

Start the instance.

Configure Proxy:

Install ProxyDroid from the Play Store.

Open it, grant root access.

Set Host: 10.0.2.2, Port: 8080, Proxy Type: HTTP. Enable it.

Install Certificate:

Open the browser, go to http://mitm.it, download and install the certificate.

Bypass Pinning:

Find the Lords Mobile APK online.

On your PC, run: certutil -p "lords_mobile.apk" (from mitmproxy's folder).

Install the generated, patched APK onto NoxPlayer.

Capture Traffic:

On your PC, run: mitmproxy -s fixed_monitor.py

Open Lords Mobile and use it. All traffic will be saved to game_traffic.db.

Analyze:

Run python fixed_analyze.py to see the captured requests and find the chat API.

Understanding the Code
fixed_monitor.py
This script is an mitmproxy addon. It hooks into two events:

def request(self, flow): - Triggered for every HTTP request sent from the game.

def response(self, flow): - Triggered for every HTTP response received by the game.

It filters out noise (Google/Facebook traffic) and saves the rest to a SQLite database.

fixed_analyze.py
This script queries the game_traffic.db SQLite file. It shows you:

How many requests were captured.

Which game servers were most active.

A preview of the data sent and received.

You will use this to find URLs like .../chat/send... or .../api/postmessage....

This document is your master key. Every problem you faced and solved is documented here. Refer to it whenever you need to set up this project again or explain your process. Well done on your perseverance


