import sys
import json

# Tool script to parse output from modified `psgplay` to produce json format (with MFP detection)
# (useful for tunes in SNDH format, without YM conversion)
# See psgplay diff below

if len(sys.argv) < 2:
    print("Usage: regdmp.py <psgplay_log_file>")
    sys.exit(1)

fn = sys.argv[1]
fd = 8000000
frid = -1
ay = dict()
ay_amps = [[], [], []]
rs = []


def get_amp_ch_freq(ch):
    lst = ay_amps[ch]
    fmin = 20
    fmax = -1
    # 1st pass - detect min, max
    for rc in lst:
        vv = rc['v']
        if vv < fmin:
            fmin = vv
        if vv > fmax:
            fmax = vv
    # find freq of going from <max to max
    med = (fmax + fmin) // 2
    prev = -1
    prev_max_ts = 0
    freqs = []
    for rc in lst:
        vv = rc['v']
        ts = rc['t']
        # ignore first value
        if vv >= med and prev >= 0 and prev < med:
            if prev_max_ts > 0:
                dt = ts - prev_max_ts
                if dt > 0:
                    freqs.append(1 / dt)
            prev_max_ts = ts
        prev = vv
    avg = 0
    if len(freqs) > 0:
        avg = sum(freqs) / len(freqs)
    return avg, fmin, fmax


def dump(idx):
    print(idx)
    ayreg = []
    for ii in range(16):
        ayreg.append(ay[ii])
    print(' YM:', ayreg)
    amps = dict()
    for ii in range(3):
        print(' C{}: {}'.format(ii, ay_amps[ii]))
        if len(ay_amps[ii]) > 1:
            fr, mn, mx = get_amp_ch_freq(ii)
            amps[ii] = [fr, mn, mx]
    rc = {'ym': ayreg, 'amp': amps}
    rs.append(rc)


def reset_ay():
    for ii in range(16):
        ay[ii] = 0


def reset_amps():
    for ii in range(3):
        ay_amps[ii] = []


reset_ay()
reset_amps()

with open(fn, 'r') as ii:
    while True:
        ln = ii.readline()
        if not ln:
            break
        if 'INT_TIMERC' in ln:
            frid += 1
            dump(frid)
            reset_amps()
        if 'REG RW' in ln:
            try:
                (tp, rst) = ln.split(' REG RW')
                (tm, reg, val) = rst.split(', ')
                reg = int(reg.strip())
                val = int(val.strip())
                tsec = int(tm) / fd
                if tp == 'YM':
                    ay[reg] = val
                    if (reg >= 8 and reg <= 10):
                        ay_amps[reg - 8].append({'t': tsec, 'v': val})
                elif tp == 'MFP':
                    # no need in this
                    pass
                else:
                    raise Exception("Unknown type {}".format(tp))
            except Exception as e:
                # skip malformed lines but print a short diagnostic
                print("Warning: failed to parse line: {!r} -> {}".format(ln.strip(), e), file=sys.stderr)

with open(fn + '.json', 'w') as json_file:
    json.dump(rs, json_file, indent=4)

############ psgplay diff against commit f44740e406065024043a5e96f0670c64a6455081

"""
diff --git a/lib/atari/mfp.c b/lib/atari/mfp.c
index ea72cb5..2423b7a 100644
--- a/lib/atari/mfp.c
+++ b/lib/atari/mfp.c
@@ -289,6 +289,11 @@ u32 mfp_irq_vector(void)
 return M68K_INT_ACK_SPURIOUS;
 }
+ // need this to detect start of YM frame, 5 is Timer C
+ if (irq == 5) {
+ printf("INT_TIMERC\n");
+ }
+
 /*
 * In-service registers ISRA and ISRB allow interrupts to
 * be nested. A bit is set whenever an interrupt vector
diff --git a/lib/atari/psg.c b/lib/atari/psg.c
index d8aff09..c27c1b9 100644
--- a/lib/atari/psg.c
+++ b/lib/atari/psg.c
@@ -248,10 +248,13 @@ static void psg_wr_u8(const struct device *device, u32 dev_address, u8 data)
 reg_select = data;
 break;
 case 2:
- case 3:
- if (reg_select < 16)
+ case 3: {
+ if (reg_select < 16) {
+ printf("YM REG RW %li, %i, %i\n", machine_cycle(), reg_select, data);
 psg.reg[reg_select] = data;
+ }
 break;
+ }
 default:
 BUG();
 }
"""
