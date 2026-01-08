import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import time

# --- Dependency Check ---
try:
    from PIL import ImageTk, Image
    import pygame
    import numpy as np
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    exit()

# --- Constants ---
IMAGE_FILENAME = "Futuristic chiptune converter interface.jpg"
SAMPLE_RATE = 44100
MASTER_CLOCK = 2000000  # 2MHz Clock for Atari ST
FRAME_RATE = 50         # 50Hz update rate

class YM2149Emulator:
    def __init__(self):
        self.regs = [0] * 14
        self.phase = [0.0, 0.0, 0.0]

    def update(self, regs):
        self.regs = regs

    def get_audio_chunk(self, num_samples):
        # Frequency = fMaster / (16 * TP)
        tp = [
            self.regs[0] | ((self.regs[1] & 0x0F) << 8),
            self.regs[2] | ((self.regs[3] & 0x0F) << 8),
            self.regs[4] | ((self.regs[5] & 0x0F) << 8)
        ]

        freqs = [MASTER_CLOCK / (16 * t) if t > 0 else 0 for t in tp]
        vols = [(self.regs[i] & 0x0F) / 15.0 for i in [8, 9, 10]]

        t = np.arange(num_samples) / SAMPLE_RATE
        output = np.zeros(num_samples)

        for i in range(3):
            if freqs[i] > 0:
                # Generate Square Wave
                sig = np.sign(np.sin(2 * np.pi * freqs[i] * t + self.phase[i]))
                output += sig * vols[i]
                self.phase[i] = (self.phase[i] + 2 * np.pi * freqs[i] * num_samples / SAMPLE_RATE) % (2 * np.pi)

        return (output * 0.3 * 32767).astype(np.int16)

class AtariPlayer:
    def __init__(self, root):
        self.root = root
        self.emu = YM2149Emulator()
        self.playing = False
        self.ym_data = []

        pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2) # Use 2 channels for stereo
        self.channel = pygame.mixer.Channel(0)
        self.setup_ui()

    def setup_ui(self):
        try:
            # Check if image file exists, and handle running from different directories
            if not os.path.exists(IMAGE_FILENAME):
                parent_dir_img_path = os.path.join("..", IMAGE_FILENAME)
                if os.path.exists(parent_dir_img_path):
                    img_path = parent_dir_img_path
                else:
                    raise FileNotFoundError(f"Image file not found: {IMAGE_FILENAME}")
            else:
                img_path = IMAGE_FILENAME

            img = Image.open(img_path)
            self.bg_img = ImageTk.PhotoImage(img)
            self.root.geometry(f"{img.width}x{img.height}")
            tk.Label(self.root, image=self.bg_img).place(x=0, y=0, relwidth=1, relheight=1)
        except Exception as e:
            print(f"Error loading background image: {e}")
            self.root.geometry("600x400")

        # Custom buttons placed on your GUI image
        btn_style = {"bg": "#111111", "fg": "#00FF00", "font": ("Courier", 10, "bold")}

        tk.Button(self.root, text="LOAD YM", command=self.load_file, **btn_style).place(x=50, rely=0.8)
        tk.Button(self.root, text="PLAY", command=self.play_music, **btn_style).place(x=150, rely=0.8)
        tk.Button(self.root, text="STOP", command=self.stop_music, **btn_style).place(x=250, rely=0.8)

        self.status = tk.Label(self.root, text="SYSTEM READY", bg="black", fg="#00FF00")
        self.status.place(x=50, rely=0.7)

    def load_file(self):
        self.stop_music()
        path = filedialog.askopenfilename(filetypes=[("YM Files", "*.ym")])
        if path:
            with open(path, "rb") as f:
                raw = f.read()

            # Basic format validation
            header = raw[:4]
            if header not in (b'YM5!', b'YM6!'):
                messagebox.showwarning("Unsupported Format", "This does not appear to be a YM5 or YM6 file.")
                return

            # Find data block and de-interleave
            data_start = raw.find(b'YM_dat')
            if data_start != -1:
                data = raw[data_start + len(b'YM_dat'):]
            else: # Fallback for older formats
                data = raw[34:]

            num_frames = len(data) // 14
            if num_frames == 0:
                self.status.config(text="ERROR: No frames found!")
                return

            self.ym_data = [[data[r * num_frames + f] for r in range(14)] for f in range(num_frames)]
            self.status.config(text=f"LOADED: {os.path.basename(path)}")

    def play_music(self):
        if not self.ym_data:
            self.status.config(text="No YM file loaded!")
            return
        if self.playing:
            return

        self.playing = True
        self.status.config(text="PLAYING...")
        threading.Thread(target=self._audio_loop, daemon=True).start()

    def stop_music(self):
        if self.playing:
            self.playing = False
            self.channel.stop()
            self.status.config(text="SYSTEM READY")

    def _audio_loop(self):
        chunk_size = int(SAMPLE_RATE / FRAME_RATE)

        for frame in self.ym_data:
            if not self.playing:
                break

            # Throttle the loop to prevent the sound queue from getting too large
            while self.channel.get_queue() and len(self.channel.get_queue()) > 8:
                if not self.playing: break
                time.sleep(0.01)

            if not self.playing: break

            self.emu.update(frame)

            # Generate audio chunk and convert to stereo for better compatibility
            mono_chunk = self.emu.get_audio_chunk(chunk_size)
            stereo_chunk = np.repeat(mono_chunk[:, np.newaxis], 2, axis=1)
            sound = pygame.sndarray.make_sound(stereo_chunk)

            self.channel.queue(sound)

        # Wait for the queue to finish playing
        while self.channel.get_queue() is not None:
            if not self.playing: break
            time.sleep(0.1)

        if self.playing: # Finished naturally
            self.playing = False
            self.status.config(text="SYSTEM READY")

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Atari ST YM Player")
    AtariPlayer(root)
    root.mainloop()
