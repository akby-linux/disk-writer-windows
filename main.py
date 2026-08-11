import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import sys
import threading
import time
import subprocess
import json
import webbrowser
from disk_writer import DiskWriter, DiskWriteError
from i18n import get_text

# Akby Green Edition Teması
ctk.set_appearance_mode("Dark")  # Karanlık Tema
ctk.set_default_color_theme("green")  # Yeşil vurgular

# ISO dosyası magic bytes kontrolü
ISO_MAGIC_BYTES = b'CD001'  # ISO 9660 standart tanımlayıcı


def validate_iso(filepath):
    """Seçilen dosyanın gerçek bir ISO dosyası olup olmadığını kontrol eder."""
    try:
        with open(filepath, 'rb') as f:
            # ISO 9660 tanımlayıcısı 32769. byte'ta başlar (sector 16, offset 1)
            f.seek(32769)
            magic = f.read(5)
            if magic == ISO_MAGIC_BYTES:
                return True

            # Bazı ISO'lar farklı sektörlerde olabilir, 34817 ve 36865'i de kontrol et
            for offset in [34817, 36865]:
                f.seek(offset)
                magic = f.read(5)
                if magic == ISO_MAGIC_BYTES:
                    return True

        return False
    except (IOError, OSError):
        return False


class DiskWriterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Varsayılan dil
        self.current_lang = "tr"

        self.title(get_text(self.current_lang, "window_title"))
        self.geometry("700x580")
        self.resizable(False, False)

        # Uygulama ikonu
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        if os.path.exists(icon_path):
            from PIL import Image, ImageTk
            icon_image = Image.open(icon_path).resize((64, 64), Image.LANCZOS)
            self._icon_photo = ImageTk.PhotoImage(icon_image)
            self.iconphoto(True, self._icon_photo)

        # Seçilen ISO dosyası
        self.selected_iso_path = None

        self.setup_ui()
        self.refresh_drives()

    def t(self, key):
        """Kısa yol: mevcut dilde çeviri al"""
        return get_text(self.current_lang, key)

    def setup_ui(self):
        # Ana Çerçeve
        self.main_frame = ctk.CTkFrame(self, corner_radius=15)
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        # ── Üst Bar: Başlık + Dil Seçimi ──
        self.top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.top_bar.pack(fill="x", padx=25, pady=(15, 0))

        # Dil seçici (sağ üst köşe)
        self.lang_frame = ctk.CTkFrame(self.top_bar, fg_color="transparent")
        self.lang_frame.pack(side="right")

        self.lang_label = ctk.CTkLabel(self.lang_frame, text=self.t("lang_label"), font=ctk.CTkFont(size=11), text_color="gray")
        self.lang_label.pack(side="left", padx=(0, 5))

        self.lang_combo = ctk.CTkComboBox(
            self.lang_frame,
            values=["Türkçe", "English"],
            width=100,
            height=25,
            font=ctk.CTkFont(size=11),
            command=self._on_language_change,
            state="readonly"
        )
        self.lang_combo.set("Türkçe")
        self.lang_combo.pack(side="left")

        # Başlık
        self.title_label = ctk.CTkLabel(self.main_frame, text=self.t("app_title"), font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.pack(pady=(5, 5))

        self.subtitle_label = ctk.CTkLabel(self.main_frame, text=self.t("subtitle"), font=ctk.CTkFont(size=12), text_color="gray")
        self.subtitle_label.pack(pady=(0, 20))

        # ── 1. Adım: ISO Seçimi ──
        self.step1_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.step1_frame.pack(fill="x", padx=25, pady=8)

        self.iso_label = ctk.CTkLabel(self.step1_frame, text=self.t("step1_label"), font=ctk.CTkFont(size=13, weight="bold"))
        self.iso_label.grid(row=0, column=0, sticky="w")

        self.iso_path_label = ctk.CTkLabel(self.step1_frame, text=self.t("iso_not_selected"), text_color="gray", anchor="w")
        self.iso_path_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 8))

        self.select_iso_btn = ctk.CTkButton(self.step1_frame, text=self.t("btn_select_iso"), command=self.select_iso, width=200)
        self.select_iso_btn.grid(row=2, column=0, padx=(0, 10), sticky="w")

        self.website_btn = ctk.CTkButton(
            self.step1_frame,
            text=self.t("btn_website"),
            command=self.open_website,
            width=200,
            fg_color="#1f538d",
            hover_color="#163d6b"
        )
        self.website_btn.grid(row=2, column=1, padx=5, sticky="w")

        self.website_info_label = ctk.CTkLabel(self.step1_frame, text=self.t("website_info"), text_color="gray", font=ctk.CTkFont(size=11))
        self.website_info_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ── 2. Adım: USB Sürücü Seçimi ──
        self.step2_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.step2_frame.pack(fill="x", padx=25, pady=(15, 8))

        self.usb_label = ctk.CTkLabel(self.step2_frame, text=self.t("step2_label"), font=ctk.CTkFont(size=13, weight="bold"))
        self.usb_label.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.usb_combo = ctk.CTkComboBox(self.step2_frame, values=[self.t("usb_searching")], width=350, state="readonly")
        self.usb_combo.grid(row=1, column=0, padx=(0, 10), sticky="w")

        self.refresh_btn = ctk.CTkButton(self.step2_frame, text=self.t("btn_refresh"), command=self.refresh_drives, width=90)
        self.refresh_btn.grid(row=1, column=1, padx=5, sticky="w")

        self.usb_info_label = ctk.CTkLabel(self.step2_frame, text=self.t("usb_info"), text_color="gray", font=ctk.CTkFont(size=11))
        self.usb_info_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # ── 3. Adım: Yazdırma ve İlerleme ──
        self.step3_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.step3_frame.pack(fill="x", padx=25, pady=(20, 10))

        self.status_label = ctk.CTkLabel(self.step3_frame, text=self.t("status_ready"), text_color="gray")
        self.status_label.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(self.step3_frame)
        self.progress_bar.pack(fill="x", pady=10)
        self.progress_bar.set(0)

        # Yazdır Butonu
        self.write_btn = ctk.CTkButton(
            self.main_frame,
            text=self.t("btn_write"),
            font=ctk.CTkFont(size=16, weight="bold"),
            height=45,
            width=250,
            command=self.start_writing
        )
        self.write_btn.pack(pady=(10, 20))

    def _on_language_change(self, choice):
        """Dil değiştiğinde tüm arayüzü güncelle"""
        self.current_lang = "en" if choice == "English" else "tr"
        self._refresh_ui_texts()

    def _refresh_ui_texts(self):
        """Tüm arayüz metinlerini mevcut dile göre güncelle"""
        self.title(self.t("window_title"))
        self.title_label.configure(text=self.t("app_title"))
        self.subtitle_label.configure(text=self.t("subtitle"))
        self.iso_label.configure(text=self.t("step1_label"))
        self.lang_label.configure(text=self.t("lang_label"))

        # ISO seçilmediyse placeholder'ı güncelle
        if not self.selected_iso_path:
            self.iso_path_label.configure(text=self.t("iso_not_selected"))

        self.select_iso_btn.configure(text=self.t("btn_select_iso"))
        self.website_btn.configure(text=self.t("btn_website"))
        self.website_info_label.configure(text=self.t("website_info"))
        self.usb_label.configure(text=self.t("step2_label"))
        self.refresh_btn.configure(text=self.t("btn_refresh"))
        self.usb_info_label.configure(text=self.t("usb_info"))
        self.status_label.configure(text=self.t("status_ready"))
        self.write_btn.configure(text=self.t("btn_write"))

    def select_iso(self):
        filepath = filedialog.askopenfilename(
            title=self.t("iso_dialog_title"),
            filetypes=((self.t("iso_file_types"), "*.iso"), (self.t("all_files"), "*.*"))
        )
        if filepath:
            # ISO doğrulama
            if not validate_iso(filepath):
                self.status_label.configure(text=self.t("iso_invalid"), text_color="#e85050")
                messagebox.showwarning(
                    self.t("write_error_title"),
                    self.t("iso_invalid")
                )
                return

            self.selected_iso_path = filepath
            filename = os.path.basename(filepath)
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.iso_path_label.configure(text=f"✔ {filename} ({file_size_mb:.0f} MB)", text_color="#2fa572")
            self.status_label.configure(text=self.t("iso_selected"), text_color="white")

    def open_website(self):
        """Akby Linux Green Edition indirme sayfasını tarayıcıda açar."""
        webbrowser.open("https://akbylinux.org/green.html")
        self.status_label.configure(text=self.t("browser_opened"), text_color="#e8a838")

    def refresh_drives(self):
        """
        Sadece çıkarılabilir (removable) USB sürücüleri tespit eder.
        - Windows: Win32 API ile DRIVE_REMOVABLE kontrolü
        - Linux: /sys/block/<dev>/removable dosyasını kontrol eder
        """
        drives = []

        if os.name == 'nt':
            # ── Windows: WMI ile çıkarılabilir sürücüleri bul ──
            try:
                import ctypes
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    if bitmask & 1:
                        drive_path = f"{letter}:\\"
                        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                        # DRIVE_REMOVABLE = 2
                        if drive_type == 2:
                            try:
                                total, used, free = 0, 0, 0
                                import shutil
                                usage = shutil.disk_usage(drive_path)
                                gb_size = round(usage.total / (1024**3), 1)
                                drives.append(f"{letter}: - {gb_size} GB")
                            except:
                                drives.append(f"{letter}: - (Boyut okunamadı)")
                    bitmask >>= 1
            except Exception as e:
                print(f"Windows sürücü tespiti hatası: {e}")

        else:
            # ── Linux: lsblk ile çıkarılabilir USB cihazları bul ──
            try:
                result = subprocess.run(
                    ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,RM,TRAN,MODEL"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    for device in data.get("blockdevices", []):
                        # RM=1 → Removable, TRAN=usb → USB bağlantılı
                        is_removable = device.get("rm") in (True, "1", 1)
                        is_usb = device.get("tran") == "usb"
                        dev_type = device.get("type", "")

                        if (is_removable or is_usb) and dev_type == "disk":
                            dev_name = device.get("name", "?")
                            dev_size = device.get("size", "?")
                            dev_model = device.get("model", "").strip() if device.get("model") else ""

                            label = f"/dev/{dev_name} - {dev_size}"
                            if dev_model:
                                label += f" ({dev_model})"
                            drives.append(label)
            except Exception as e:
                print(f"Linux sürücü tespiti hatası: {e}")

        if not drives:
            drives = [self.t("usb_not_found")]

        self.usb_combo.configure(values=drives)
        self.usb_combo.set(drives[0])

    def start_writing(self):
        if not self.selected_iso_path:
            self.status_label.configure(text=self.t("err_no_iso"), text_color="#e85050")
            return

        selected_drive = self.usb_combo.get()
        if "bulunamadı" in selected_drive.lower() or "not found" in selected_drive.lower():
            self.status_label.configure(text=self.t("err_no_usb"), text_color="#e85050")
            return

        # Onay penceresi
        confirm_msg = self.t("confirm_message").format(
            drive=selected_drive,
            iso=os.path.basename(self.selected_iso_path)
        )
        confirm = messagebox.askyesno(
            self.t("confirm_title"),
            confirm_msg,
            icon="warning"
        )

        if not confirm:
            self.status_label.configure(text=self.t("cancelled"), text_color="gray")
            return

        self.status_label.configure(text=self.t("writing_started"), text_color="white")

        # Arayüzü kilitle
        self._set_ui_locked(True)

        # Gerçek yazdırma işlemi
        self.current_writer = DiskWriter(
            iso_path=self.selected_iso_path,
            target_device=selected_drive,
            progress_callback=lambda v: self.after(0, self.progress_bar.set, v),
            status_callback=lambda m: self.after(0, self.status_label.configure, text=m, text_color="white")
        )

        def do_write():
            try:
                self.current_writer.write()
                self.after(0, self._on_write_success)
            except DiskWriteError as e:
                self.after(0, self._on_write_error, str(e))
            except Exception as e:
                self.after(0, self._on_write_error, f"Beklenmeyen hata: {e}")

        threading.Thread(target=do_write, daemon=True).start()

    def _set_ui_locked(self, locked):
        """Yazdırma sırasında arayüz elemanlarını kilitle/aç"""
        state = "disabled" if locked else "normal"
        self.select_iso_btn.configure(state=state)
        self.website_btn.configure(state=state)
        self.refresh_btn.configure(state=state)
        self.lang_combo.configure(state="disabled" if locked else "readonly")
        self.usb_combo.configure(state="disabled" if locked else "readonly")

        if locked:
            self.write_btn.configure(text=self.t("btn_cancel"), fg_color="#c0392b", hover_color="#a93226", command=self._cancel_write)
        else:
            self.write_btn.configure(text=self.t("btn_write"), fg_color=["#2CC985", "#2FA572"], hover_color=["#0C955A", "#106A43"], command=self.start_writing)

    def _cancel_write(self):
        """Yazdırma işlemini iptal et"""
        if hasattr(self, 'current_writer'):
            self.current_writer.cancel()
        self.status_label.configure(text=self.t("cancelling"), text_color="#e8a838")

    def _on_write_success(self):
        """Yazdırma başarıyla tamamlandığında"""
        self._set_ui_locked(False)
        self.progress_bar.set(1.0)
        self.status_label.configure(
            text=self.t("write_success"),
            text_color="#2fa572"
        )

    def _on_write_error(self, error_msg):
        """Yazdırma sırasında hata oluştuğunda"""
        self._set_ui_locked(False)
        self.progress_bar.set(0)
        self.status_label.configure(text=f"⚠ {error_msg}", text_color="#e85050")
        messagebox.showerror(self.t("write_error_title"), error_msg)


if __name__ == "__main__":
    app = DiskWriterApp()
    app.mainloop()
