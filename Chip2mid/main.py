import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import time
import wave

# --- Dependency Check ---
missing_modules = []
try:
    from PIL import ImageTk, Image, ImageGrab
except ImportError:
    missing_modules.append("Pillow")
try:
    import pygame
except ImportError:
    missing_modules.append("pygame")
try:
    import numpy as np
except ImportError:
    missing_modules.append("numpy")
try:
    import lhafile
except ImportError:
    missing_modules.append("lhafile")

# --- Local Imports ---
from ym_parser import YMParser
from psg_emulator import YM2149

if missing_modules:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        message = f"The following required modules are missing: {', '.join(missing_modules)}\n\n"
        message += "Please install them by running this command in your terminal:\n"
        message += f"pip install {' '.join(m.lower() for m in missing_modules)}"
        messagebox.showerror("Missing Dependencies", message)
    except ImportError:
        print(f"ERROR: Missing required modules: {', '.join(missing_modules)}")
        print(f"Please install them by running: pip install {' '.join(m.lower() for m in missing_modules)}")
    exit()

# --- Constants ---
SAMPLE_RATE = 44100
MASTER_CLOCK = 2000000
FRAME_RATE = 50

class AtariPlayer:
    def __init__(self, root, screenshot_mode=False):
        self.root = root
        self.emu = YM2149(MASTER_CLOCK, SAMPLE_RATE)
        self.playing = False
        self.ym_data = []
        self.monitor_thread = None
        self.screenshot_mode = screenshot_mode

        pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1)
        self.channel = pygame.mixer.Channel(0)
        self.setup_ui()

        if self.screenshot_mode:
            self.root.after(500, self.take_screenshot_and_exit) # Wait for UI to draw

    def take_screenshot_and_exit(self):
        x = self.root.winfo_rootx()
        y = self.root.winfo_rooty()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save("/home/jules/verification/verification.png")
        self.root.destroy()

    def setup_ui(self):
        img_path = None
        for ext in ['.jpg', '.png']:
            filename = "Futuristic chiptune converter interface" + ext
            if os.path.exists(os.path.join("..", filename)):
                 img_path = os.path.join("..", filename)
                 break
            elif os.path.exists(filename):
                img_path = filename
                break

        try:
            if img_path:
                img = Image.open(img_path)
                self.bg_img = ImageTk.PhotoImage(img)
                self.root.geometry(f"{img.width}x{img.height}")
                tk.Label(self.root, image=self.bg_img).place(x=0, y=0, relwidth=1, relheight=1)
            else:
                if not self.screenshot_mode:
                    messagebox.showerror("Error", "Background image not found.")
                self.root.geometry("600x400")
        except Exception as e:
            if not self.screenshot_mode:
                messagebox.showerror("Error", f"Failed to load image: {e}")
            self.root.geometry("600x400")

        btn_style = {"bg": "#111111", "fg": "#00FF00", "font": ("Courier", 10, "bold")}
        tk.Button(self.root, text="LOAD YM", command=self.load_file, **btn_style).place(x=50, rely=0.8)
        tk.Button(self.root, text="PLAY", command=self.play_music, **btn_style).place(x=150, rely=0.8)
        tk.Button(self.root, text="STOP", command=self.stop_music, **btn_style).place(x=250, rely=0.8)
        self.status = tk.Label(self.root, text="SYSTEM READY", bg="black", fg="#00FF00")
        self.status.place(x=50, rely=0.7)

    def load_file(self):
        self.stop_music()
        path = filedialog.askopenfilename(filetypes=[("YM Files", "*.ym")])
        if not path: return
        self.status.config(text="PARSING...")
        self.root.update_idletasks()
        self.parser = YMParser()
        if self.parser.parse(path):
            self.status.config(text=f"LOADED: {os.path.basename(path)}")
            self.ym_data = self.parser.frames
        else:
            messagebox.showerror("Error", "Failed to parse YM file.")
            self.status.config(text="ERROR")
            self.ym_data = []

    def play_music(self):
        if not self.ym_data:
            self.status.config(text="No file loaded!")
            return
        if self.playing: return
        self.playing = True
        self.status.config(text="RENDERING...")
        self.root.update_idletasks()

        audio_data = self.render_audio(self.parser)
        sound = pygame.sndarray.make_sound(audio_data)

        self.channel.play(sound)
        self.status.config(text="PLAYING...")
        self.monitor_thread = threading.Thread(target=self._monitor_playback, daemon=True)
        self.monitor_thread.start()

    def render_audio(self, parser):
        self.emu.reset()
        header = parser.header
        frames = parser.frames
        samples_per_frame = int(SAMPLE_RATE / header['frame_rate_hz'])
        all_samples = []
        for frame_regs in frames:
            for reg, val in enumerate(frame_regs):
                if reg < 14: # YM has 14 regs, emu has 16
                    self.emu.write_register(reg, val)
            # Handle reg 13 (envelope shape) special case
            if frame_regs[13] != 0xFF:
                self.emu.write_register(13, frame_regs[13])

            frame_samples = self.emu.generate_samples(samples_per_frame)
            all_samples.extend(frame_samples)

        # Convert to 16-bit PCM for pygame
        pcm_data = (np.array(all_samples) * 32767).astype(np.int16)
        return pcm_data

    def stop_music(self):
        self.playing = False
        self.channel.stop()
        self.status.config(text="SYSTEM READY")

    def _monitor_playback(self):
        while self.channel.get_busy():
            if not self.playing: return
            time.sleep(0.1)
        if self.playing:
            self.playing = False
            self.status.config(text="SYSTEM READY")

if __name__ == "__main__":
    import sys
    screenshot_mode = '--screenshot' in sys.argv
    root = tk.Tk()
    root.title("Atari ST YM Player")
    player = AtariPlayer(root, screenshot_mode=screenshot_mode)
    def on_closing():
        player.stop_music()
        if player.monitor_thread and player.monitor_thread.is_alive():
            player.monitor_thread.join()
        pygame.quit()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_closing)
    if not screenshot_mode:
        root.mainloop()
