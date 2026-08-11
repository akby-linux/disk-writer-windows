# disk_writer.py - ISO to USB Yazdırma Motoru
# Akby Linux Disk Writer for Windows
# Windows ve Linux desteği

import os
import subprocess
import time

CHUNK_SIZE = 1024 * 1024  # 1MB parçalar halinde yaz


class DiskWriteError(Exception):
    """Disk yazma sırasında oluşan hatalar"""
    pass


class DiskWriter:
    """
    ISO dosyasını USB sürücüye raw olarak yazan motor.
    Windows'ta Win32 API, Linux'ta doğrudan dosya yazımı kullanır.
    """

    def __init__(self, iso_path, target_device, progress_callback=None, status_callback=None):
        """
        iso_path: ISO dosyasının yolu
        target_device: Windows'ta "E: - 16.0 GB", Linux'ta "/dev/sdb - 16G (Kingston)"
        progress_callback: function(percentage: float) - 0.0 ile 1.0 arası
        status_callback: function(message: str) - durum mesajları
        """
        self.iso_path = iso_path
        self.target_device = target_device
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.cancelled = False
        self._start_time = None

    def cancel(self):
        """Yazdırma işlemini iptal et"""
        self.cancelled = True

    def _update_progress(self, value):
        if self.progress_callback:
            self.progress_callback(min(value, 1.0))

    def _update_status(self, msg):
        if self.status_callback:
            self.status_callback(msg)

    def _format_speed(self, bytes_written, elapsed):
        """Yazma hızını hesapla ve formatla"""
        if elapsed <= 0:
            return "Hesaplanıyor..."
        speed = bytes_written / elapsed
        if speed >= 1024 * 1024:
            return f"{speed / (1024 * 1024):.1f} MB/s"
        elif speed >= 1024:
            return f"{speed / 1024:.1f} KB/s"
        else:
            return f"{speed:.0f} B/s"

    def write(self):
        """ISO'yu hedef sürücüye yaz. İşletim sistemine göre uygun yöntemi seçer."""
        if not os.path.exists(self.iso_path):
            raise DiskWriteError(f"ISO dosyası bulunamadı: {self.iso_path}")

        iso_size = os.path.getsize(self.iso_path)
        if iso_size == 0:
            raise DiskWriteError("ISO dosyası boş!")

        self._start_time = time.time()

        if os.name == 'nt':
            return self._write_windows(iso_size)
        else:
            return self._write_linux(iso_size)

    # ══════════════════════════════════════════════
    #  WINDOWS - Win32 API ile Raw Disk Yazma
    # ══════════════════════════════════════════════

    def _write_windows(self, iso_size):
        """Windows'ta USB'ye ISO yazdırma (Win32 API)"""
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        # Ctypes tanımlamaları (64-bit Handle kesilmesini önlemek için çok kritik!)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        
        kernel32.DeviceIoControl.restype = wintypes.BOOL
        kernel32.WriteFile.restype = wintypes.BOOL
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.FlushFileBuffers.restype = wintypes.BOOL

        def is_invalid_handle(h):
            return h in (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF, None)

        # ── Win32 Sabitleri ──
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 1
        FILE_SHARE_WRITE = 2
        OPEN_EXISTING = 3
        FSCTL_LOCK_VOLUME = 0x00090018
        FSCTL_DISMOUNT_VOLUME = 0x00090020
        IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080

        # Sürücü harfini ayıkla (örn: "E: - 16.0 GB" → "E")
        drive_letter = self.target_device.split(":")[0].strip()
        if len(drive_letter) > 1:
            drive_letter = drive_letter[-1]
        volume_path = f"\\\\.\\{drive_letter}:"

        # ── 1. Hacmi (Volume) aç ──
        self._update_status("Sürücü açılıyor...")
        h_volume = kernel32.CreateFileW(
            volume_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None
        )

        if is_invalid_handle(h_volume):
            error = ctypes.get_last_error()
            raise DiskWriteError(
                f"Sürücüye erişilemedi ({volume_path}). Hata kodu: {error}\n\n"
                "ÖNEMLİ: Ekranda Windows'un 'Diski Biçimlendir' (Format) uyarısı varsa lütfen 'İptal'e basıp kapatın. "
                "Ardından tekrar 'Yazdır' butonuna basmayı deneyin."
            )

        physical_drive_num = None
        try:
            # ── 2. Fiziksel sürücü numarasını öğren ──
            self._update_status("Fiziksel sürücü tespit ediliyor...")

            class STORAGE_DEVICE_NUMBER(ctypes.Structure):
                _fields_ = [
                    ('DeviceType', ctypes.c_ulong),
                    ('DeviceNumber', ctypes.c_ulong),
                    ('PartitionNumber', ctypes.c_ulong),
                ]

            sdn = STORAGE_DEVICE_NUMBER()
            bytes_returned = wintypes.DWORD()

            result = kernel32.DeviceIoControl(
                h_volume, IOCTL_STORAGE_GET_DEVICE_NUMBER,
                None, 0,
                ctypes.byref(sdn), ctypes.sizeof(sdn),
                ctypes.byref(bytes_returned), None
            )

            if not result:
                raise DiskWriteError("Fiziksel sürücü numarası alınamadı.")

            physical_drive_num = sdn.DeviceNumber

            # ── 3. Hacmi kilitle ve bağlantısını kes ──
            self._update_status("Sürücü kilitleniyor...")
            kernel32.DeviceIoControl(
                h_volume, FSCTL_LOCK_VOLUME,
                None, 0, None, 0,
                ctypes.byref(bytes_returned), None
            )

            self._update_status("Sürücü bağlantısı kesiliyor...")
            kernel32.DeviceIoControl(
                h_volume, FSCTL_DISMOUNT_VOLUME,
                None, 0, None, 0,
                ctypes.byref(bytes_returned), None
            )

            # ── 4. Fiziksel sürücüyü yazma için aç ──
            physical_drive = f"\\\\.\\PhysicalDrive{physical_drive_num}"
            self._update_status(f"Fiziksel sürücü açılıyor: {physical_drive}")

            h_drive = kernel32.CreateFileW(
                physical_drive,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None, OPEN_EXISTING, 0, None
            )

            if is_invalid_handle(h_drive):
                error = ctypes.get_last_error()
                raise DiskWriteError(f"Fiziksel sürücü açılamadı ({physical_drive}). Hata: {error}")

            try:
                # ── 5. ISO dosyasını parça parça yaz ──
                bytes_written_total = 0
                iso_size_mb = iso_size / (1024 * 1024)

                self._update_status("ISO dosyası yazılıyor...")

                with open(self.iso_path, 'rb') as iso_file:
                    while True:
                        if self.cancelled:
                            raise DiskWriteError("İşlem kullanıcı tarafından iptal edildi.")

                        chunk = iso_file.read(CHUNK_SIZE)
                        if not chunk:
                            break

                        # Son parçayı 512-byte sektör sınırına hizala
                        if len(chunk) % 512 != 0:
                            chunk += b'\x00' * (512 - len(chunk) % 512)

                        bytes_written = wintypes.DWORD()
                        result = kernel32.WriteFile(
                            h_drive, chunk, len(chunk),
                            ctypes.byref(bytes_written), None
                        )

                        if not result:
                            error = ctypes.get_last_error()
                            raise DiskWriteError(f"Yazma hatası! Hata kodu: {error}")

                        bytes_written_total += bytes_written.value
                        progress = bytes_written_total / iso_size
                        self._update_progress(progress)

                        elapsed = time.time() - self._start_time
                        speed = self._format_speed(bytes_written_total, elapsed)
                        written_mb = bytes_written_total / (1024 * 1024)
                        self._update_status(
                            f"Yazılıyor... {written_mb:.0f} MB / {iso_size_mb:.0f} MB  ({speed})"
                        )

                # Tamponu temizle
                self._update_status("Tampon temizleniyor (sync)...")
                kernel32.FlushFileBuffers(h_drive)

            finally:
                kernel32.CloseHandle(h_drive)

        finally:
            kernel32.CloseHandle(h_volume)

        self._update_progress(1.0)
        return True

    # ══════════════════════════════════════════════
    #  LINUX - Doğrudan /dev/sdX yazma
    # ══════════════════════════════════════════════

    def _write_linux(self, iso_size):
        """Linux'ta USB'ye ISO yazdırma"""
        # Cihaz adını ayıkla (örn: "/dev/sdb - 16G (Kingston)" → "/dev/sdb")
        device = self.target_device.split(" - ")[0].strip()

        if not device.startswith("/dev/"):
            raise DiskWriteError(f"Geçersiz cihaz: {device}")

        # ── 1. Tüm bölümleri (partition) unmount et ──
        self._update_status("Sürücü bağlantısı kesiliyor...")
        for i in range(1, 10):
            subprocess.run(["umount", f"{device}{i}"], capture_output=True, timeout=10)

        iso_size_mb = iso_size / (1024 * 1024)

        # ── 2. ISO'yu doğrudan cihaza yaz ──
        try:
            with open(self.iso_path, 'rb') as iso_file:
                with open(device, 'wb') as usb_dev:
                    bytes_written_total = 0

                    while True:
                        if self.cancelled:
                            raise DiskWriteError("İşlem kullanıcı tarafından iptal edildi.")

                        chunk = iso_file.read(CHUNK_SIZE)
                        if not chunk:
                            break

                        usb_dev.write(chunk)
                        bytes_written_total += len(chunk)

                        progress = bytes_written_total / iso_size
                        self._update_progress(progress)

                        elapsed = time.time() - self._start_time
                        speed = self._format_speed(bytes_written_total, elapsed)
                        written_mb = bytes_written_total / (1024 * 1024)
                        self._update_status(
                            f"Yazılıyor... {written_mb:.0f} MB / {iso_size_mb:.0f} MB  ({speed})"
                        )

                    # Tampon temizle
                    self._update_status("Tampon temizleniyor (sync)...")
                    usb_dev.flush()
                    os.fsync(usb_dev.fileno())

        except PermissionError:
            raise DiskWriteError(
                "Yetki hatası! Programı 'sudo' ile çalıştırın.\n"
                "Örnek: sudo python3 main.py"
            )
        except FileNotFoundError:
            raise DiskWriteError(f"Cihaz bulunamadı: {device}\nUSB çıkarılmış olabilir.")
        except OSError as e:
            raise DiskWriteError(f"Yazma hatası: {e}")

        # Son sync
        subprocess.run(["sync"], capture_output=True, timeout=30)

        self._update_progress(1.0)
        return True
