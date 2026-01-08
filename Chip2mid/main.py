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

class YM2149Emulator:
    def __init__(self):
        self.regs = np.zeros(14, dtype=np.uint8)
        self.reset()

    def reset(self):
        self.tone_period = np.zeros(3, dtype=np.uint16)
        self.tone_counter = np.zeros(3, dtype=np.float64)
        self.tone_output = np.ones(3, dtype=np.int8)
        self.noise_period = 0
        self.noise_counter = 0.0
        self.noise_rng = 1
        self.noise_output = 1
        self.env_period = 0
        self.env_counter = 0.0
        self.env_shape = 0
        self.env_holding = False
        self.env_step = 0
        self.amp = np.zeros(3, dtype=np.float32)

        # Pre-calculated volume table for non-envelope mode
        self.volume_table = np.array([
            0.0, 0.014, 0.02, 0.028, 0.04, 0.056, 0.08, 0.112,
            0.16, 0.224, 0.31, 0.44, 0.62, 0.88, 1.24, 1.76
        ]) / 1.76

    def update(self, regs):
        self.regs = np.array(regs, dtype=np.uint8)
        # Update internal state based on registers
        self.tone_period[0] = self.regs[0] | ((self.regs[1] & 0x0F) << 8)
        self.tone_period[1] = self.regs[2] | ((self.regs[3] & 0x0F) << 8)
        self.tone_period[2] = self.regs[4] | ((self.regs[5] & 0x0F) << 8)
        self.noise_period = self.regs[6] & 0x1F
        self.env_period = self.regs[11] | (self.regs[12] << 8)

        new_env_shape = self.regs[13]
        if new_env_shape != 0xFF: # 0xFF is a special value meaning "don't change"
            if self.env_shape != new_env_shape:
                 self.env_shape = new_env_shape
                 # Trigger envelope attack (reset)
                 self.env_holding = False
                 self.env_step = 0
                 self.env_counter = 0

    def get_audio_chunk(self, num_samples):
        output = np.zeros(num_samples)

        # Clock rate for each component
        tone_clock_step = float(MASTER_CLOCK) / (16 * SAMPLE_RATE)
        noise_clock_step = float(MASTER_CLOCK) / (16 * SAMPLE_RATE)
        env_clock_step = float(MASTER_CLOCK) / (256 * SAMPLE_RATE)

        for i in range(num_samples):
            # --- Tone Generators ---
            for c in range(3):
                self.tone_counter[c] += tone_clock_step
                if self.tone_counter[c] >= self.tone_period[c]:
                    self.tone_counter[c] = 0
                    self.tone_output[c] *= -1

            # --- Noise Generator (LFSR) ---
            self.noise_counter += noise_clock_step
            if self.noise_counter >= self.noise_period:
                self.noise_counter = 0
                # Simple 17-bit LFSR
                self.noise_rng = (self.noise_rng >> 1) ^ (0x24000 if (self.noise_rng & 1) else 0)
                self.noise_output = (self.noise_rng & 1) * 2 - 1

            # --- Envelope Generator ---
            if not self.env_holding:
                self.env_counter += env_clock_step
                if self.env_counter >= self.env_period:
                    self.env_counter = 0
                    self.env_step += 1
                    if self.env_step > 15:
                        self.env_step = 15
                        # Handle envelope shape looping/holding
                        if self.env_shape < 4 or (self.env_shape >= 8 and self.env_shape < 12):
                            self.env_holding = True # Hold
                        elif self.env_shape < 8:
                            self.env_step = 0 # Loop
                        else: # Shapes >= 12
                             self.env_step = 15 if self.env_shape in [12, 14] else 0

            # Determine volume for each channel
            for c in range(3):
                use_envelope = (self.regs[8+c] & 0x10) > 0
                if use_envelope:
                    # Envelope shapes are complex, this is a simplified version
                    vol_idx = self.env_step if self.env_shape < 8 else 15 - self.env_step
                    self.amp[c] = self.volume_table[vol_idx]
                else:
                    self.amp[c] = self.volume_table[self.regs[8+c] & 0x0F]

            # --- Mixer ---
            mixer = self.regs[7]
            sample = 0.0
            for c in range(3):
                 # Tone enabled?
                tone_on = (mixer & (1 << c)) == 0
                 # Noise enabled?
                noise_on = (mixer & (8 << c)) == 0

                signal = self.tone_output[c] if tone_on else 1.0
                signal = min(signal, self.noise_output if noise_on else 1.0)

                sample += signal * self.amp[c]

            output[i] = sample / 3.0 # Average the 3 channels

        return (output * 32767).astype(np.int16)

class AtariPlayer:
    def __init__(self, root):
        self.root = root
        self.emu = YM2149Emulator()
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
        # Reset emulator state before loading a new file
        self.emu.reset()
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

        # --- Register Stream Logging ---
        try:
            with open("register_dump.txt", "w") as f:
                f.write("Frame, R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13\n")
                for i, frame_regs in enumerate(self.ym_data):
                    # Format as hex for easier comparison with debuggers
                    regs_str = ", ".join(f"{val:02X}" for val in frame_regs)
                    f.write(f"{i}, {regs_str}\n")
            self.status.config(text="Register dump written.")
        except Exception as e:
            messagebox.showerror("Logging Error", f"Failed to write register dump: {e}")
            return # Don't proceed if logging fails
        # --- End Logging ---

        self.playing = True
        self.status.config(text="GENERATING...")
        self.root.update_idletasks() # Update UI

        # Pre-generate all audio chunks
        chunk_size = int(SAMPLE_RATE / FRAME_RATE)
        all_sounds = []
        full_mono_audio = np.array([], dtype=np.int16)
        for frame in self.ym_data:
            self.emu.update(frame)
            mono_chunk = self.emu.get_audio_chunk(chunk_size)
            full_mono_audio = np.concatenate((full_mono_audio, mono_chunk))
            stereo_chunk = np.repeat(mono_chunk.reshape(-1, 1), 2, axis=1)
            all_sounds.append(pygame.sndarray.make_sound(stereo_chunk))

        # --- Save to WAV file for testing ---
        try:
            with wave.open("output.wav", "w") as wf:
                wf.setnchannels(1) # Mono
                wf.setsampwidth(2) # 16-bit
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(full_mono_audio.tobytes())
            self.status.config(text="WAV saved.")
        except Exception as e:
            messagebox.showerror("WAV Error", f"Failed to save WAV file: {e}")
        # --- End WAV save ---

        if not all_sounds:
            self.status.config(text="ERROR: No sound data.")
            self.playing = False
            return

        # Pygame's queue handles seamless playback
        self.channel.play(all_sounds[0])
        for sound in all_sounds[1:]:
            self.channel.queue(sound)

        self.status.config(text="PLAYING...")

        # Start a thread to monitor when playback is finished
        self.monitor_thread = threading.Thread(target=self._monitor_playback, daemon=True)
        self.monitor_thread.start()

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
