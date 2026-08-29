# Windows'ta Dikte

*[English](README.windows.md)*

Dikte, Windows 10 ve 11'de doğrudan çalışır. Kayıt ffmpeg'in DirectShow
girişinden geçer, pano ve yapıştırma doğrudan Win32 API'yi kullanır, global
kısayol `RegisterHotKey` ile kaydedilir; yani Python, PyQt6 ve ffmpeg dışında
kuracağın bir şey yok.

## Kurulum

```powershell
winget install Gyan.FFmpeg Python.Python.3.13
python -m pip install PyQt6
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` PATH'ine bir `dikte` komutu, Başlat menüsü girdisi, açılışta
başlatma girdisi ve iki global kısayol ekler. Yönetici olarak değil, kendi
kullanıcınla çalıştır: her şey senin profiline kurulur.

Sonra başlat:

```powershell
dikte
```

Ayarlar penceresi ilk açılışta gelir. İndirmek için bir konuşma modeli seç, ya
da yerine bir OpenAI veya OpenRouter anahtarı ekle.

## Kullanım

`Ctrl+Space`'e bas, konuş, tekrar bas. Transkript temizlenir ve o an yazdığın
pencereye yapıştırılır. Tepsi ikonu aynı kontrolleri taşır; üstüne toplantı,
ajan ve ayarlar.

## İki Windows sınırı

- **Yönetici pencereleri.** Windows, bir programın yönetici olarak çalışan bir
  pencereye tuş göndermesine izin vermez ve bu başarısızlığı bildirmez. Böyle bir
  pencereye dikte ettiğinde metin yine panoya düşer; `Ctrl+V`'ye kendin bas.
- **Toplantı sesi.** Bir toplantının karşı tarafını kaydetmek loopback bir cihaz
  ister: sürücün sunuyorsa "Stereo Mix", sunmuyorsa VB-Cable. macOS'ta
  BlackHole'un oynadığı rolün aynısı. Ayarlar > Toplantı altından seç.

## GPU

Dikte'nin indirdiği llama.cpp derlemeleri Vulkan kullanır; NVIDIA, AMD ve Intel
kartlarını kapsar. CUDA derlemesi kendi ayrı çalışma-zamanı indirmesini ister, o
gerekiyorsa Ayarlar'ı kendi `llama-server.exe`'ne yönelt.

## Güncelleme ve kaldırma

```powershell
powershell -ExecutionPolicy Bypass -File update.ps1      # çeker ve yeniden kurar, kısayolların kalır
powershell -ExecutionPolicy Bypass -File uninstall.ps1   # Dikte'yi kaldırır, ayarlar ve dikteler kalır
```

Ayarlar ve verini de silmek için `uninstall.ps1`'e `-Purge` geç.
