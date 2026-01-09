import struct
import lhafile

class YMParser:
    def __init__(self):
        self.header = {}
        self.frames = []

    def parse(self, file_path):
        """
        Parses a YM file, handling LHA decompression if necessary.
        Returns True on success, False on failure.
        """
        try:
            raw_data = None
            if lhafile.is_lhafile(file_path):
                lha = lhafile.LhaFile(file_path)
                # Assume the first file in the archive is the correct one
                filename = lha.namelist()[0]
                raw_data = lha.read(filename)
            else:
                with open(file_path, "rb") as f:
                    raw_data = f.read()

            if not raw_data:
                print("Error: Could not read data from file.")
                return False

            if not self._parse_header(raw_data):
                return False

            if not self._parse_frames(raw_data):
                return False

            return True
        except Exception as e:
            print(f"Error parsing YM file: {e}")
            return False

    def _parse_header(self, data):
        """
        Parses the header of the YM file data.
        """
        try:
            magic = data[:4].decode('ascii')
            if not magic.startswith('YM'):
                print(f"Error: Invalid YM magic number: {magic}")
                return False

            check_string = data[4:12].decode('ascii')
            if check_string != "LeOnArD!":
                print("Warning: YM check string is not 'LeOnArD!'")

            (
                num_frames,
                song_attributes,
                num_digidrum_samples,
                master_clock_hz,
                frame_rate_hz,
                loop_frame,
            ) = struct.unpack('>IHHIIH', data[12:30])

            # Skip over reserved section
            offset = 30

            # Read digidrum samples if they exist
            if num_digidrum_samples > 0:
                # For now, we are not processing digidrums, just skipping them.
                # This needs to be implemented for full YM6 support.
                # Each digidrum has a 4-byte size header, so we skip all of them.
                for _ in range(num_digidrum_samples):
                    size = struct.unpack('>I', data[offset:offset+4])[0]
                    offset += 4 + size

            # Read null-terminated strings for song metadata
            song_name = self._read_c_string(data, offset)
            offset += len(song_name) + 1
            author_name = self._read_c_string(data, offset)
            offset += len(author_name) + 1
            song_comment = self._read_c_string(data, offset)
            offset += len(song_comment) + 1

            # End of header marker
            end_marker = data[offset:offset+4]
            if end_marker != b'End!':
                 # In some files, the end marker is missing. We just use the current offset.
                 print("Warning: YM end marker 'End!' not found. Assuming data starts here.")
            else:
                offset += 4

            self.header = {
                'magic': magic,
                'num_frames': num_frames,
                'song_attributes': song_attributes,
                'num_digidrum_samples': num_digidrum_samples,
                'master_clock_hz': master_clock_hz,
                'frame_rate_hz': frame_rate_hz,
                'loop_frame': loop_frame,
                'song_name': song_name,
                'author_name': author_name,
                'song_comment': song_comment,
                'data_offset': offset
            }

            # YM specific flags
            self.header['interleaved'] = (song_attributes & 0x01) != 0

            return True
        except (struct.error, IndexError, UnicodeDecodeError) as e:
            print(f"Error parsing YM header: {e}")
            return False

    def _read_c_string(self, data, offset):
        """Helper to read a null-terminated string from a byte array."""
        end = data.find(b'\0', offset)
        if end == -1:
            return ""
        return data[offset:end].decode('latin-1')

    def _parse_frames(self, data):
        """
        Parses the AY/YM register frames from the data.
        """
        try:
            offset = self.header['data_offset']
            num_frames = self.header['num_frames']
            frame_data = data[offset:]

            # 14 registers for AY/YM
            num_regs = 14

            # The last 4 bytes are an 'End!' marker for some older formats, but we've handled that.
            # However, some files might not have it, so we need to be careful with the length.
            expected_len = num_frames * num_regs
            if len(frame_data) < expected_len:
                print(f"Warning: Frame data is shorter than expected. Got {len(frame_data)}, expected {expected_len}.")
                # Adjust num_frames if data is truncated
                num_frames = len(frame_data) // num_regs
                self.header['num_frames'] = num_frames

            if self.header['interleaved']:
                # Data is stored as R0F0, R0F1, ..., R1F0, R1F1, ...
                self.frames = []
                for f in range(num_frames):
                    frame = []
                    for r in range(num_regs):
                        frame.append(frame_data[r * num_frames + f])
                    self.frames.append(frame)
            else:
                # Data is stored as R0F0, R1F0, ..., R0F1, R1F1, ...
                self.frames = []
                for f in range(num_frames):
                    frame = []
                    for r in range(num_regs):
                        frame.append(frame_data[f * num_regs + r])
                    self.frames.append(frame)

            # The Rust parser also mentions a possible 16 registers for YM6 variants
            # For now, we are sticking to 14, which covers most files.

            return True
        except (IndexError, struct.error) as e:
            print(f"Error parsing YM frames: {e}")
            return False
