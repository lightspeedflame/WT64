import numpy as np

class YM2149:
    def __init__(self, master_clock, sample_rate):
        self.master_clock = master_clock
        self.sample_rate = sample_rate
        self.clock_ratio = master_clock / (16 * sample_rate)

        self.regs = np.zeros(16, dtype=np.uint8)
        self.reset()

    def reset(self):
        # Tone Generators
        self.tone_periods = np.zeros(3, dtype=np.uint16)
        self.tone_counters = np.zeros(3, dtype=np.float64)
        self.tone_outputs = np.ones(3, dtype=np.int8)

        # Noise Generator
        self.noise_period = 0
        self.noise_counter = 0.0
        self.noise_rng = 1
        self.noise_output = 1

        # Envelope Generator
        self.env_period = 0
        self.env_counter = 0.0
        self.env_shape = 0
        self.env_step = 0
        self.env_holding = False

        # Mixer & Volume
        self.volumes = np.zeros(3, dtype=np.float32)

        # Pre-calculated volume table (logarithmic scale is more accurate)
        self.volume_table = np.array([
            0.0, 0.014, 0.02, 0.028, 0.04, 0.056, 0.08, 0.112,
            0.16, 0.224, 0.31, 0.44, 0.62, 0.88, 1.24, 1.76
        ]) / 1.76

    def set_registers(self, frame_regs):
        """
        Update the PSG registers and internal state from a frame's data.
        """
        # YM files have 14 registers, but the chip has 16. We map them.
        for i in range(len(frame_regs)):
             # Only update if the register value has changed
            if self.regs[i] != frame_regs[i]:
                self.regs[i] = frame_regs[i]

        # Register values are latched into the PSG's internal components
        self.tone_periods[0] = self.regs[0] | ((self.regs[1] & 0x0F) << 8)
        self.tone_periods[1] = self.regs[2] | ((self.regs[3] & 0x0F) << 8)
        self.tone_periods[2] = self.regs[4] | ((self.regs[5] & 0x0F) << 8)

        self.noise_period = self.regs[6] & 0x1F

        self.env_period = self.regs[11] | (self.regs[12] << 8)

        # A write to register 13 resets the envelope generator
        if len(frame_regs) > 13 and frame_regs[13] != 0xFF: # 0xFF is a special "no-op" value in some YM logs
            self.env_shape = frame_regs[13]
            self.env_step = 0
            self.env_counter = 0
            self.env_holding = False

    def tick(self):
        """
        Advances the PSG state by one sample clock tick and returns a mixed sample.
        """
        # --- Tone Generators ---
        for i in range(3):
            self.tone_counters[i] += self.clock_ratio
            if self.tone_counters[i] >= self.tone_periods[i]:
                self.tone_counters[i] %= self.tone_periods[i] if self.tone_periods[i] > 0 else 1
                self.tone_outputs[i] *= -1

        # --- Noise Generator (LFSR) ---
        self.noise_counter += self.clock_ratio
        noise_period_clocks = self.noise_period if self.noise_period > 0 else 1
        if self.noise_counter >= noise_period_clocks:
            self.noise_counter %= noise_period_clocks
            # 17-bit LFSR (from Rust reference)
            self.noise_rng = (self.noise_rng >> 1) ^ (0x24000 if (self.noise_rng & 1) else 0)
            self.noise_output = (self.noise_rng & 1)

        # --- Envelope Generator ---
        if not self.env_holding:
            self.env_counter += self.clock_ratio / 2 # Envelope clock is slower
            if self.env_counter >= self.env_period:
                self.env_counter %= self.env_period if self.env_period > 0 else 1
                self.env_step += 1
                if self.env_step > 15:
                    self.env_step = 15 # Clip at max
                    shape = self.env_shape & 0b1111
                    if shape < 4 or (shape >= 8 and shape < 12):
                        self.env_holding = True # Hold level
                    elif shape < 8: # Continue
                        pass
                    else: # Attack/Decay shapes
                        self.env_step = 0 if (shape & 0b0010) else 15

        # --- Mixer & Volume ---
        mixer = self.regs[7]
        final_sample = 0.0

        for i in range(3):
            # Volume
            use_envelope = (self.regs[8+i] & 0x10) != 0
            if use_envelope:
                shape = self.env_shape & 0b1111
                vol_idx = self.env_step
                # Invert for attack shapes
                if shape < 4 or (shape >= 8 and shape < 12 and (self.env_shape & 0b0100)):
                    vol_idx = 15 - vol_idx
                self.volumes[i] = self.volume_table[vol_idx & 0x0F]
            else:
                self.volumes[i] = self.volume_table[self.regs[8+i] & 0x0F]

            # Mix signals
            tone_on = (mixer & (1 << i)) == 0
            noise_on = (mixer & (8 << i)) == 0

            signal = 1.0
            if tone_on:
                signal = min(signal, self.tone_outputs[i])
            if noise_on:
                signal = min(signal, self.noise_output)

            final_sample += signal * self.volumes[i]

        return final_sample / 3.0 # Average the 3 channels
