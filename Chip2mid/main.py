import tkinter as tk
from tkinter import filedialog, messagebox
import os
import threading
import time
import wave

# --- Dependency Check ---
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

# --- Local Imports ---
from ym_parser import YMParser
from psg_emulator import PSG

if missing_modules:
    # We need tkinter to show the error, but it might not be the missing one.
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
        # Fallback to console if tkinter itself is missing
        print(f"ERROR: Missing required modules: {', '.join(missing_modules)}")
        print(f"Please install them by running: pip install {' '.join(m.lower() for m in missing_modules)}")
    exit()

# --- Constants ---
SAMPLE_RATE = 44100
MASTER_CLOCK = 2000000  # 2MHz Clock for Atari ST
FRAME_RATE = 50         # 50Hz update rate

class AtariPlayer:
    def __init__(self, root):
        self.root = root
        self.emu = None # To be replaced with the new PSG emulator
        self.playing = False
        self.ym_data = []
        self.monitor_thread = None

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

        self.status.config(text="PARSING...")
        self.root.update_idletasks()

        self.parser = YMParser()
        if self.parser.parse(path):
            self.status.config(text=f"LOADED: {os.path.basename(path)}")
            # For simplicity, we keep the raw frame data handy for the play function
            self.ym_data = self.parser.frames
        else:
            messagebox.showerror("Parsing Error", "Failed to parse the YM file. Check console for details.")
            self.status.config(text="ERROR: Parse failed")
            self.ym_data = [] # Clear any old data

    def play_music(self):
        if not self.ym_data:
            self.status.config(text="No YM file loaded!")
            return
        if self.playing:
            return

        self.playing = True

        # Render the audio to a WAV file
        full_mono_audio = self.render_to_wav(self.parser)

        # Convert mono PCM to stereo for pygame
        stereo_audio = np.repeat(full_mono_audio.reshape(-1, 1), 2, axis=1)

        # Create a single pygame Sound object from the full audio data
        sound = pygame.sndarray.make_sound(stereo_audio)

        if not sound:
            self.status.config(text="ERROR: Sound generation failed.")
            self.playing = False
            return

        # Play the sound
        self.channel.play(sound)

        self.status.config(text="PLAYING...")

        # Start a thread to monitor when playback is finished
        self.monitor_thread = threading.Thread(target=self._monitor_playback, daemon=True)
        self.monitor_thread.start()

    def render_to_wav(self, parser, output_path="output.wav"):
        """
        Renders the parsed YM data to a WAV file.
        Returns the raw mono audio data as a numpy array.
        """
        self.status.config(text="RENDERING...")
        self.root.update_idletasks()

        header = parser.header
        frames = parser.frames

        # Initialize the PSG emulator with parameters from the YM file
        self.emu = PSG(header['master_clock_hz'], SAMPLE_RATE)

        samples_per_frame = int(SAMPLE_RATE / header['frame_rate_hz'])
        total_samples = samples_per_frame * len(frames)

        audio_buffer = np.zeros(total_samples, dtype=np.float32)

        for i, frame_regs in enumerate(frames):
            self.emu.set_registers(frame_regs)
            start_sample = i * samples_per_frame
            for j in range(samples_per_frame):
                audio_buffer[start_sample + j] = self.emu.tick()

        # Normalize and convert to 16-bit PCM
        max_val = np.max(np.abs(audio_buffer))
        if max_val > 0:
            audio_buffer /= max_val

        pcm_data = (audio_buffer * 32767).astype(np.int16)

        # --- Save to WAV file ---
        try:
            with wave.open(output_path, "w") as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm_data.tobytes())
            self.status.config(text="WAV saved.")
        except Exception as e:
            messagebox.showerror("WAV Error", f"Failed to save WAV file: {e}")

        return pcm_data

    def stop_music(self):
        self.playing = False # This acts as a signal to the monitor thread
        self.channel.stop()
        self.status.config(text="SYSTEM READY")

    def _monitor_playback(self):
        """Monitors the audio channel and updates status when done."""
        while self.channel.get_busy():
            if not self.playing: # Stop was called
                return
            time.sleep(0.1)

        # If the loop finishes and we weren't manually stopped, the song ended.
        if self.playing:
            self.playing = False
            self.status.config(text="SYSTEM READY")

if __name__ == "__main__":
    root = tk.Tk()
    root.title("Atari ST YM Player")
    player = AtariPlayer(root)

    def on_closing():
        player.stop_music()
        pygame.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
