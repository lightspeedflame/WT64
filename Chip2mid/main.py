import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import time

# --- Dependency Check ---
def check_dependencies():
    missing_modules = []
    try:
        from PIL import ImageTk, Image
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

    if missing_modules:
        root = tk.Tk()
        root.withdraw()  # Hide the main window
        message = f"The following required modules are missing: {', '.join(missing_modules)}\n\n"
        message += "Please install them by running this command in your terminal:\n"
        message += f"pip install {' '.join(m.lower() for m in missing_modules)}"
        messagebox.showerror("Missing Dependencies", message)
        exit()

check_dependencies()

# --- Constants ---
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
        img_path = None
        # Check for both .jpg and .png versions of the image
        for ext in ['.jpg', '.png']:
            filename = "Futuristic chiptune converter interface" + ext
            if os.path.exists(filename):
                img_path = filename
                break
            elif os.path.exists(os.path.join("..", filename)):
                img_path = os.path.join("..", filename)
                break

        try:
            if img_path:
                img = Image.open(img_path)
                self.bg_img = ImageTk.PhotoImage(img)
                self.root.geometry(f"{img.width}x{img.height}")
                tk.Label(self.root, image=self.bg_img).place(x=0, y=0, relwidth=1, relheight=1)
            else:
                # If the image is not found, show an error and set a default size
                messagebox.showerror(
                    "Error: Image Not Found",
                    "The background image ('Futuristic chiptune converter interface.jpg' or .png) was not found.\n\nPlease make sure the image file is in the same directory as the application."
                )
                self.root.geometry("600x400")
        except Exception as e:
            # Catch other potential errors with image loading
            messagebox.showerror("Error", f"An unexpected error occurred while loading the image: {e}")
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
        if not path:
            return

        try:
            with open(path, "rb") as f:
                raw_data = f.read()

            # Check for LHA compression
            if lhafile.is_lhafile(path):
                lha = lhafile.LhaFile(path)
                # Assuming the first file in the archive is the one we want
                filename = lha.namelist()[0]
                raw_data = lha.read(filename)

            # Now, process the (potentially decompressed) raw_data
            header = raw_data[:4]
            if header not in (b'YM5!', b'YM6!', b'YM2!', b'YM3!', b'YM3b'):
                 messagebox.showwarning("Unsupported Format", f"Unsupported YM format or invalid file: {header.decode('ascii', 'ignore')}")
                 return

            # Simple de-interleaver for YM5/YM6 files
            # Note: This is a simplified parser. A more robust solution would
            # properly parse the full header to find the data offset.
            data_start = raw_data.find(b'YM_dat')
            if data_start != -1:
                data = raw_data[data_start + len(b'YM_dat'):]
            else: # Fallback for older formats
                data = raw_data[34:]

            num_frames = len(data) // 14
            if num_frames == 0:
                self.status.config(text="ERROR: No frames found!")
                return

            # De-interleave the register data
            self.ym_data = [[data[r * num_frames + f] for r in range(14)] for f in range(num_frames)]
            self.status.config(text=f"LOADED: {os.path.basename(path)}")

        except Exception as e:
            messagebox.showerror("Error Loading File", f"An error occurred while loading the file:\n{e}")
            self.status.config(text="ERROR: Load failed")

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
