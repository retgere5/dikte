# Dikte on Windows

*[Türkçe](README.windows.tr.md)*

Dikte runs natively on Windows 10 and 11. Recording goes through ffmpeg's
DirectShow input, the clipboard and paste use the Win32 API directly, and the
global shortcut is registered with `RegisterHotKey`, so there is nothing to
install beyond Python, PyQt6 and ffmpeg.

## Install

```powershell
winget install Gyan.FFmpeg Python.Python.3.13
python -m pip install PyQt6
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` adds a `dikte` command to your PATH, a Start menu entry, an
autostart entry, and the two global shortcuts. Run it as yourself, not as
administrator: everything lands in your own user profile.

Then start it:

```powershell
dikte
```

The settings window opens on first run. Pick a speech model to download, or add
an OpenAI or OpenRouter key instead.

## Using it

Press `Ctrl+Space`, talk, and press it again. The transcript is cleaned up and
pasted into whatever window you were typing in. The tray icon carries the same
controls, plus meetings, the agent, and settings.

## Two Windows limits

- **Elevated windows.** Windows will not let one program send keystrokes to a
  window running as administrator, and it does not report the failure. When you
  dictate into such a window the text still lands on the clipboard; press
  `Ctrl+V` yourself.
- **Meeting audio.** Recording the far side of a meeting needs a loopback
  device: "Stereo Mix" where your driver offers it, or VB-Cable where it does
  not. It is the same role BlackHole plays on macOS. Pick it under Settings,
  Meeting.

## GPU

The llama.cpp builds Dikte fetches use Vulkan, which covers NVIDIA, AMD and
Intel cards. A CUDA build needs its own separate runtime download, so if that is
the one you want, point Settings at a `llama-server.exe` of your own.

## Update and remove

```powershell
powershell -ExecutionPolicy Bypass -File update.ps1      # pull and reinstall, keeping your shortcuts
powershell -ExecutionPolicy Bypass -File uninstall.ps1   # remove Dikte, leaving settings and dictations
```

Pass `-Purge` to `uninstall.ps1` to remove your settings and data as well.
