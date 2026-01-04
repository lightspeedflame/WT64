import math
import mido
import lhafile
import struct
import json
import sys

channels = []
tp2freq = []  # 12 bits / 4096 values - [note, wheel_val]
vol2midi = []  # 16 values
sid2freq = []  # for sidFx - 256 * 7 values - [note, wheel_val]
sidsinus2freq = []  # for sinus sidFx - 256 * 7 values - [note, wheel_val]

tmo = None

chip_clk_zx = 1773400
chip_clk_ym = 2000000
chip_clk = None

notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

ppq = None
mbpm = None  # midi bpm (in microsec)
ticks_per_frame = 0
start_midi_frame = 0
freq_period = 0
ymFx = False
jsonFmt = False

sid_tp = [0, 0]
sid_tc = [0, 0]

env_data = {'l': 0, 'h': 0, 'p': 0, 's': 0}

# each AY/YM channel may produce multiple MIDI tracks, i.e. one per specific sound type below
# it is to simplify further editing of MIDI file, i.e. applying effects, setting instruments
TRK_NORMAL = 'Voice'
TRK_SID = 'Sid'
TRK_SIDSIN = 'Sidsinus'
TRK_SIDBUZZ = 'Sidbuzz'
TRK_EV = 'Ev'
TRK_NOISE = 'Noise'

# want to save to midi file in this order
tracks_order = (TRK_NORMAL, TRK_NOISE, TRK_EV, TRK_SID, TRK_SIDSIN, TRK_SIDBUZZ)
tone_type_short = {TRK_NORMAL: 'T', TRK_EV: 'E', TRK_SID: 'S', TRK_SIDSIN: 'I', TRK_SIDBUZZ: 'B'}


class Time(object):
    # this "time" is in interrupt frames count
    def __init__(self):
        self.time = 0

    def increase(self):
        self.time += 1

    def get(self):
        return self.time

    def dump(self):
        mm = int(self.time / freq_period / 60 % 60)
        ss = int(self.time / freq_period % 60)
        fr = int(self.time % freq_period)
        return "{:5} {:02}:{:02}.{:<3} ".format(self.time, mm, ss, fr)


class Channel(object):
    def __init__(self, number, midi_file):
        self.t_on = False
        self.n_on = False
        self.vol = 0
        self.vol_mod = False
        self.number = number
        self.midi_file = midi_file
        self.noise_p = 0
        self.note = -1
        self.tph = 0
        self.tpl = 0
        self.prev_note = None
        self.prev_noise_p = None
        self.playt = False
        self.prev_playt = False
        self.playn = False
        self.prev_playn = False
        self.prev_vol = 0
        self.tracks = dict()
        self.sid_track = None
        self.sidsin_track = None
        self.sid_track = None
        self.time = None
        self.wheel = 0
        self.prev_wheel = 0
        self.sid_id = -1
        self.sid_type = 0
        self.ev_tone = False
        self.note_track = None  # last track were note played
        self.note_track_type = TRK_NORMAL  # type of track of last played note
        self.track_times = dict()
        for tt in tracks_order:
            self.track_times[tt] = start_midi_frame
        self.track_type = None
        self.jfreq = None  # note frequency set externally (ie from json file)

    def set_on(self, flag):
        self.t_on = not (flag & 2 ** self.number)
        self.n_on = not (flag & 2 ** (3 + self.number))

    def set_vol(self, val):
        self.vol = val & 15
        self.vol_mod = val & 16

    def set_noise(self, val):
        self.noise_p = val & 31

    def set_tone_period_hi(self, val):
        self.tph = val

    def set_tone_period_low(self, val):
        self.tpl = val

    def enable_sid(self, sid, stype):
        self.sid_id = sid
        self.sid_type = stype

    def disable_sid(self, sid):
        if self.sid_id == sid:
            self.sid_id = -1

    def process(self, tmo):
        self.time = tmo.get()
        self.prev_note = self.note
        self.prev_wheel = self.wheel
        self.prev_playt = self.playt
        self.prev_playn = self.playn

        tone_period = None
        self.ev_tone = False

        if self.sid_id >= 0:
            # literally any if jfreq is set
            tone_period = 1 if self.jfreq else sid_tp[self.sid_id]
        elif self.vol_mod and (env_data['s'] == 10 or env_data['s'] == 14):
            tone_period = env_data['l'] + 256 * env_data['h']
            self.ev_tone = True
            self.vol = 15
        else:
            tone_period = self.tph * 256 + self.tpl

        if tone_period == 0:
            self.note = -1
        elif self.ev_tone:
            self.note, self.wheel = note_from_ev(tone_period)
            self.wheel = 0
            self.track_type = TRK_EV
        elif self.sid_id >= 0:
            if self.sid_type == 0:
                if self.jfreq:
                    self.note, self.wheel = get_note_wheel_from_freq(self.jfreq)
                else:
                    self.note = note_from_sid(sid_tp[self.sid_id], sid_tc[self.sid_id])
                    self.wheel = wheel_from_sid(sid_tp[self.sid_id], sid_tc[self.sid_id])
                self.track_type = TRK_SID
            elif self.sid_type == 2:
                # sinus sid
                if self.jfreq:
                    self.note, self.wheel = get_note_wheel_from_freq(self.jfreq)
                else:
                    self.note = note_from_sinsid(sid_tp[self.sid_id], sid_tc[self.sid_id])
                    self.wheel = wheel_from_sinsid(sid_tp[self.sid_id], sid_tc[self.sid_id])
                self.track_type = TRK_SIDSIN
            elif self.sid_type == 3:
                self.note = note_from_sid(sid_tp[self.sid_id], sid_tc[self.sid_id])
                self.wheel = wheel_from_sid(sid_tp[self.sid_id], sid_tc[self.sid_id])
                self.track_type = TRK_SIDBUZZ
            else:
                self.note = note_from_tp(tone_period)
                self.wheel = wheel_from_tp(tone_period)
                self.track_type = TRK_NORMAL
        else:
            self.note = note_from_tp(tone_period)
            self.wheel = wheel_from_tp(tone_period)
            self.track_type = TRK_NORMAL

        # sid voice if enabled, ignored possible tone off value
        self.playt = (self.t_on or self.ev_tone or self.sid_id >= 0) and self.vol > 0 and self.note >= 0
        self.playn = self.n_on and self.vol > 0

    def post_process(self):
        self.prev_vol = self.vol
        self.prev_noise_p = self.noise_p

    def dump(self):
        note_tx = "{}{}".format(notes[self.note % 12], int(self.note / 12 - 2)) if self.note >= 0 else ''
        note_change = True
        if self.prev_note == self.note and \
           self.prev_playt == True and \
           self.prev_vol >= self.vol:  # take volume changes into consideration
            # don't copy same note if it didn't change
            note_tx = ''
            note_change = False

        if self.playt:
            e_t = "{} {:<4}".format(tone_type_short[self.track_type], note_tx)
        else:
            e_t = " "

        if self.prev_playt == True and self.playt == False:
            e_t = '======'
            self.note_off()
        elif self.playt and note_change:
            # new note
            if self.prev_note >= 0:
                self.note_off()
            if self.note >= 0:
                self.note_on()
        elif self.playt and self.prev_vol != self.vol:
            self.send_volume()
        if self.playt and self.prev_wheel != self.wheel:
            self.send_wheel()

        if self.playn:
            play_new = True
            if self.prev_playn:
                if self.prev_noise_p == self.noise_p \
                   and self.prev_vol >= self.vol:
                    play_new = False
            if self.prev_vol != self.vol:
                self.send_volume(noise=True)
            else:
                self.note_off(noise=True)
            if play_new:
                self.note_on(noise=True)
        elif self.prev_playn:
            self.note_off(noise=True)

        e_n = "N{:<2}".format(self.noise_p) if self.playn else " "
        if self.prev_playn == True and self.playn == False:
            e_n = '==='

        vol = "V{:<2}{}".format(self.vol & 15, "M" if self.vol_mod else " ")
        return "{} {} {}".format(e_t, e_n, vol)

    def get_etime(self, noise=False):
        # check if track was created
        trk_type = TRK_NOISE if noise else self.note_track_type
        if not trk_type in self.tracks:
            return -1
        return ticks_per_frame * (self.time - self.track_times[trk_type])

    def note_on(self, noise=False):
        trk_type = TRK_NOISE if noise else self.track_type
        if not trk_type in self.tracks:
            track = self.midi_file.add_track("Channel {} {}".format(chr(65 + self.number), trk_type))
            self.tracks[trk_type] = track
        track = self.tracks[trk_type]
        if not noise:
            self.note_track = self.tracks[self.track_type]
            self.note_track_type = self.track_type
        etime = self.get_etime(noise)
        if etime < 0:
            return
        note = 48 + 31 - self.noise_p if noise else self.note
        msg = mido.Message('note_on', channel=self.number, note=note, velocity=vol2midi[self.vol], time=etime)
        track.append(msg)
        if not noise:
            msg = mido.Message('pitchwheel', channel=self.number, pitch=self.wheel, time=0)
            track.append(msg)
        self.track_times[trk_type] = self.time

    def note_off(self, noise=False):
        trk_type = TRK_NOISE if noise else self.note_track_type
        etime = self.get_etime(noise)
        if etime < 0:
            return
        track = self.tracks[TRK_NOISE] if noise else self.note_track
        prev_note = 48 + 31 - self.prev_noise_p if noise else self.prev_note
        msg = mido.Message('note_off', channel=self.number, note=prev_note, velocity=100, time=etime)
        if track:
            track.append(msg)
        self.track_times[trk_type] = self.time

    def send_volume(self, noise=False):
        trk_type = TRK_NOISE if noise else self.note_track_type
        etime = self.get_etime(noise)
        if etime < 0:
            return
        track = self.tracks[TRK_NOISE] if noise else self.note_track
        prev_note = 48 + 31 - self.prev_noise_p if noise else self.prev_note
        msg = mido.Message('polytouch', channel=self.number, note=prev_note, value=vol2midi[self.vol], time=etime)
        track.append(msg)
        self.track_times[trk_type] = self.time

    def send_wheel(self):
        etime = self.get_etime()
        if etime < 0:
            return
        msg = mido.Message('pitchwheel', channel=self.number, pitch=self.wheel, time=etime)
        self.note_track.append(msg)
        self.track_times[self.note_track_type] = self.time

    def set_jfreq(self, val):
        self.jfreq = val


def read_psg(fn):
    with open(fn, 'rb') as ii:
        dx = ii.read()
    return dx


import os
import subprocess
def read_ym(fn):
    # many YM files are stored in LHA archives; try to open with lhafile,
    # but if that fails, read raw file bytes.
    try:
        with lhafile.LhaFile(fn) as f:
            return f.read(f.namelist()[0])
    except Exception as e:
        print(f"Error reading LHA file: {e}", file=sys.stderr)
        with open(fn, 'rb') as f:
            return f.read()


def read_json(fn):
    with open(fn, 'r') as ff:
        dx = json.load(ff)
    return dx


def dump_channels():
    tx = []
    for ch in channels:
        ch.process(tmo)
        tx.append(ch.dump())
        ch.post_process()
    print(tmo.dump(), " | ".join(tx))


def decode_psg(dx):
    # PSG dumps sometimes contain padding or unexpected bytes.
    # We'll parse conservatively: treat bytes <16 as register selectors,
    # 254 as multi-ff marker, 255 as frame end. Any unexpected bytes are
    # appended but will be ignored by process_reg_part (it now warns instead of raising).
    dx = dx[16:] if len(dx) > 16 else dx
    ps = 0
    bg = []
    while ps < len(dx):
        b = dx[ps]
        # if register selector or special marker that is followed by a value
        if (b >= 0 and b < 16) or b == 254:
            # ensure there is a following byte; if not, break
            if ps + 1 < len(dx):
                bg.append(b)
                bg.append(dx[ps + 1])
                ps += 2
            else:
                # truncated pair, append and break
                bg.append(b)
                ps += 1
        else:
            # single byte (could be 255 or unexpected)
            bg.append(b)
            ps += 1

        # process when we see frame end or at end of data
        if bg and (bg[-1] == 255 or ps >= len(dx)):
            try:
                process_reg_part(bg)
            except Exception as e:
                # don't crash on unexpected sequences; print diagnostic and continue
                print("Warning: process_reg_part raised: {}".format(e), file=sys.stderr)
            bg = []


def decode_json(dx):
    rh = []
    for __ in range(16):
        rh.append(0)
    for ff in dx:
        ymr = ff['ym']
        amp = ff['amp']
        for chi in range(3):
            if str(chi) in amp and amp[str(chi)][0] > 0:
                fr, mn, mx = amp[str(chi)]
                ymr[8 + chi] = mx
                channels[chi].set_jfreq(fr)
                sid_tp = 0
                channels[chi].enable_sid(chi, sid_tp)
            else:
                channels[chi].disable_sid(chi)
                channels[chi].set_jfreq(None)
        for ri in range(16):
            rv = ymr[ri]
            if rv != rh[ri]:
                rh[ri] = rv
                process_reg_part([ri, rv])
        # next frame
        process_reg_part([255])


def get_ntstring(dx, stpos):
    rs = ''
    while (dx[stpos] != 0):
        rs = rs + chr(dx[stpos])
        stpos += 1
    stpos += 1
    return (rs, stpos)


def decode_ym(dx):
    """
    Support YM6 when present; otherwise try to handle common YM1-5 and raw dumps.
    - If header is 'YM6!' and magic 'LeOnArD!' use YM6 parsing.
    - If header starts with 'YM' (YM1-5), attempt to find interleaved frames or
      treat as raw 16-byte frames after a small header.
    - If file is not recognized, print diagnostic hex of first bytes and raise.
    """
    # YM6 detection
    if len(dx) >= 4 and dx[0:4] == b'YM6!':
        hdr = dx[0:4]
        mgc = dx[4:12]
        if mgc != b'LeOnArD!':
            raise Exception('Invalid magic string for YM6')
        fc = struct.unpack('>L', dx[12:16])[0]
        at = struct.unpack('>L', dx[16:20])[0]
        dc = struct.unpack('>H', dx[20:22])[0]
        hz = struct.unpack('>L', dx[22:26])[0]
        ff = struct.unpack('>H', dx[26:28])[0]
        sk = struct.unpack('>H', dx[32:34])[0]
        sp = 34
        if dc > 0:
            for __ in range(dc):
                sz = struct.unpack('>L', dx[sp:sp + 4])[0]
                sp = sp + 4 + sz
        tt, sp = get_ntstring(dx, sp)
        au, sp = get_ntstring(dx, sp)
        cm, sp = get_ntstring(dx, sp)
        if args.diagnose:
            print("YM6 header found:")
            print(f"  Frames: {fc}, Attributes: {at}, Digi-drums: {dc}, Chip freq: {hz}Hz")
            print(f"  Player freq: {ff}Hz, Loop frame: {sk}")
            print(f"  Title: {tt}, Author: {au}, Comment: {cm}")

        if (at & 1) == 1:
            # interleaved
            rh = [0] * 16
            for fi in range(fc):
                for ri in range(16):
                    rv = dx[sp + fi + ri * fc]
                    if ri == 13 and rv == 255:
                        continue
                    if rv != rh[ri]:
                        rh[ri] = rv
                        process_reg_part([ri, rv])
                process_reg_part([255])
            sp = sp + 16 * fc
        else:
            # non-interleaved
            rh = [0] * 16
            for fi in range(fc):
                for ri in range(16):
                    rv = dx[sp + fi * 16 + ri]
                    if ri == 13 and rv == 255:
                        continue
                    if rv != rh[ri]:
                        rh[ri] = rv
                        process_reg_part([ri, rv])
                process_reg_part([255])
        return

    # If file starts with 'YM' but not YM6, attempt to parse YM1-5 style
    if len(dx) >= 4 and dx[0:4] in [b'YM2!', b'YM3!', b'YM3b', b'YM5!', b'YM6!']:
        # YM1-5 have a simple header, then frames
        frames = (len(dx) - 4) // 16
        rh = [0] * 16
        pos = 4
        for fi in range(frames):
            frame = dx[pos:pos + 16]
            pos += 16
            for ri in range(16):
                rv = frame[ri]
                if ri == 13 and rv == 255:
                    continue
                if rv != rh[ri]:
                    rh[ri] = rv
                    process_reg_part([ri, rv])
            process_reg_part([255])
        return

    # If file length is exact multiple of 16, treat as raw frames
    if len(dx) > 0 and len(dx) % 16 == 0:
        frames = len(dx) // 16
        rh = [0] * 16
        pos = 0
        for fi in range(frames):
            frame = dx[pos:pos + 16]
            pos += 16
            for ri in range(16):
                rv = frame[ri]
                if ri == 13 and rv == 255:
                    continue
                if rv != rh[ri]:
                    rh[ri] = rv
                    process_reg_part([ri, rv])
            process_reg_part([255])
        return

    # Diagnostic output for unrecognized formats
    head = dx[:256]
    hexdump = ' '.join("{:02X}".format(b) for b in head)
    if args.diagnose:
        print("Unrecognized YM format. First 256 bytes:\n" + hexdump)
        print(f"File length: {len(dx)}")
        print(f"Header: {dx[:16]}")
    raise Exception("Unsupported or unrecognized YM format.")


def process_reg_part(rp):
    cur_reg = -1
    multi_ff = False
    # rp is a list of bytes representing register writes and frame markers
    for b in rp:
        if cur_reg >= 0 and cur_reg < 16:
            # data byte for previously selected register
            if cur_reg in (0, 2, 4):
                channels[int(cur_reg / 2)].set_tone_period_low(b)
            elif cur_reg in (1, 3, 5):
                channels[int((cur_reg - 1) / 2)].set_tone_period_hi(b & 15)
                if ymFx:
                    if cur_reg == 1 or cur_reg == 3:
                        sid_id = (cur_reg - 1) // 2
                        amx = b >> 4
                        # tolerant handling of many amx values:
                        # 0 -> disable; 1..7 -> enable SID voice mapping heuristically;
                        # 9..11 -> sinus; 13..15 -> buzzer
                        if amx == 0:
                            for ci in range(3):
                                channels[ci].disable_sid(sid_id)
                        elif 1 <= amx <= 7:
                            # map to channel index heuristically (wrap to 0..2)
                            ch_idx = (amx - 1) % 3
                            channels[ch_idx].enable_sid(sid_id, 0)
                        elif 9 <= amx <= 11:
                            ch_idx = (amx - 9) % 3
                            channels[ch_idx].enable_sid(sid_id, 2)
                        elif 13 <= amx <= 15:
                            ch_idx = (amx - 13) % 3
                            channels[ch_idx].enable_sid(sid_id, 3)
                        else:
                            # unknown FX type: warn and continue (do not crash)
                            print("Warning: unsupported ym fx type {}".format(amx), file=sys.stderr)
                            # Fallback to a default behavior instead of crashing
                            ch_idx = (amx - 1) % 3 if amx > 0 else 0
                            channels[ch_idx].enable_sid(sid_id, 0)
            elif cur_reg == 6:
                for ci in channels:
                    ci.set_noise(b)
                if ymFx:
                    tp = b >> 5
                    sid_tp[0] = tp
            elif cur_reg == 7:
                for ci in channels:
                    ci.set_on(b)
            elif cur_reg >= 8 and cur_reg <= 10:
                channels[cur_reg - 8].set_vol(b)
                if ymFx and cur_reg == 8:
                    tp = b >> 5
                    sid_tp[1] = tp
            elif cur_reg == 11:
                env_data['l'] = b
            elif cur_reg == 12:
                env_data['h'] = b
            elif cur_reg == 13:
                env_data['s'] = b & 15
            elif ymFx and cur_reg in (14, 15):
                sid_tc[cur_reg - 14] = b
            cur_reg = -1
        elif b == 255:
            dump_channels()
            tmo.increase()
        elif b == 254:
            multi_ff = True
        elif multi_ff:
            for __ in range(4 * b):
                dump_channels()
                tmo.increase()
            multi_ff = False
        elif b >= 0 and b < 16:
            cur_reg = b
        else:
            # instead of raising, warn and continue to be tolerant with various dump formats
            print("Warning: Can't handle byte {}".format(b), file=sys.stderr)


def note_from_tp(tp):
    return tp2freq[tp][0]


def wheel_from_tp(tp):
    return tp2freq[tp][1]


def note_from_sid(tp, tc):
    return sid2freq[(tp - 1) * 256 + tc][0]


def wheel_from_sid(tp, tc):
    return sid2freq[(tp - 1) * 256 + tc][1]


def note_from_sinsid(tp, tc):
    return sidsinus2freq[(tp - 1) * 256 + tc][0]


def wheel_from_sinsid(tp, tc):
    return sidsinus2freq[(tp - 1) * 256 + tc][1]


def note_from_ev(evp):
    freq = chip_clk / 256 / evp / 2
    midi_note, midi_wheel = get_note_wheel_from_freq(freq)
    return midi_note, midi_wheel


def get_note_wheel_from_freq(freq):
    note = 12 * math.log(freq * 32 / 261.63) / math.log(2)
    midi_note = math.floor(0.5 + note)
    midi_wheel = int((note - midi_note) * 8192 / 2)
    if midi_note > 127:
        midi_note = 127
    return midi_note, midi_wheel


def build_tp_table():
    for tpi in range(4096):
        if tpi == 0:
            tpi = 1
        freq = chip_clk / 16 / tpi
        midi_note, midi_wheel = get_note_wheel_from_freq(freq)
        tp2freq.append([midi_note, midi_wheel])


def build_vol_table():
    for vi in range(16):
        # not exactly but close to AY
        vol2midi.append(int(127 * ((vi / 15) ** 3)))


def build_sid_table():
    mp = [4, 10, 16, 50, 64, 100, 200]
    for mi in range(len(mp)):
        tp = mp[mi]
        for tc in range(256):
            if tc == 0:
                tc = 1
            freq = 2457600 / tp / tc
            midi_note, midi_wheel = get_note_wheel_from_freq(freq)
            sid2freq.append([midi_note, midi_wheel])
            # sinus sid is 8-byte sample of "sinus" wave (accordingly to ay_emul/sndh)
            sinfreq = 2457600 / tp / tc / 8
            midi_note, midi_wheel = get_note_wheel_from_freq(sinfreq)
            sidsinus2freq.append([midi_note, midi_wheel])


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', help='input psg file', required=True)
    parser.add_argument('-c', '--clock', help='chip clock (zx - default, ym)', default='zx')
    parser.add_argument('-n', '--n16-frames', help='number of frames for 1/16 note', default='6')
    parser.add_argument('-s', '--start-midi-frame', help='number of start frame, default = 0', default='0')
    parser.add_argument('-f', '--freq-period', help='psg dump frequency (Hz), default = 50', default='50')
    parser.add_argument('-o', '--output', help='output midi file', default='title.mid')
    parser.add_argument('--diagnose', action='store_true', help='print structured header info and sample frames for failing YM files')
    args = parser.parse_args()

    # clock selection
    if args.clock == 'zx':
        chip_clk = chip_clk_zx
    elif args.clock == 'ym':
        chip_clk = chip_clk_ym
    else:
        raise Exception("unsupported chip clock type: {}".format(args.clock))

    start_midi_frame = int(args.start_midi_frame)
    freq_period = int(args.freq_period)
    ticks_per_frame = 8 * 50 // freq_period
    bpm = 60 * freq_period / 4 / int(args.n16_frames)
    mtmp = mido.bpm2tempo(bpm)
    ppq = int(ticks_per_frame * mtmp / (1000000 / freq_period))

    tmid = mido.MidiFile()
    tmid.ticks_per_beat = ppq

    build_tp_table()
    build_vol_table()

    for ci in range(3):
        channels.append(Channel(ci, tmid))

    tmo = Time()

    # read input by extension (case-insensitive)
    lower_ifl = args.input.lower()
    if lower_ifl.endswith(".psg"):
        dx = read_psg(args.input)
        decode_psg(dx)
    elif lower_ifl.endswith(".json"):
        jsonFmt = True
        dx = read_json(args.input)
        decode_json(dx)
    elif lower_ifl.endswith(".ym"):
        ymFx = True
        build_sid_table()
        dx = read_ym(args.input)
        decode_ym(dx)
    elif lower_ifl.endswith(".ay"):
        # try direct AY handling (some .ay files are raw PSG dumps)
        try:
            dx = read_psg(args.input)
            if not dx:
                print("Warning: Input file is empty.", file=sys.stderr)
                sys.exit(1)
            if dx[:4] == b'ZXAY': # AyEmul header
                print("This .ay file appears to be an AyEmul file, not a raw PSG dump.", file=sys.stderr)
                print("Please use a tool like Ay_Emul to convert it to a raw .psg file.", file=sys.stderr)
                sys.exit(1)
            decode_psg(dx)
        except Exception as e:
            # provide clearer diagnostic
            print("AY input handling failed: {}".format(e), file=sys.stderr)
            print("If this is a raw PSG dump, it may be corrupted.", file=sys.stderr)
            print("If it is an AyEmul file, please use a tool like Ay_Emul to convert it to a raw .psg file.", file=sys.stderr)
            sys.exit(1)
    else:
        raise Exception("Can't handle input file extension {}".format(args.input))

    # compose real midi file now
    mid = mido.MidiFile()
    mid.ticks_per_beat = ppq
    tempo_track = mid.add_track("Tempo track")
    tempo_track.append(mido.MetaMessage('set_tempo', tempo=mtmp))

    # remap tracks so that each track has its own channel
    channel = 0
    for ci in range(3):
        cts = channels[ci].tracks
        for ti in tracks_order:
            if ti in cts:
                nt = mid.add_track(cts[ti].name)
                nt += cts[ti]
                for ev in nt:
                    if 'channel' in ev.dict():
                        ev.channel = channel
                channel += 1
                if channel > 15:
                    raise Exception("Too many MIDI channels")

    mid.save(args.output)
    print("Midi saved to {}".format(args.output))