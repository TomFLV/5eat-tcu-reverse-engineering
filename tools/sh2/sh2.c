/* A native SH-2E interpreter for driving the Denso TCU firmware.
 *
 * WHY. The Ghidra p-code emulator was measured at roughly twenty thousand
 * instructions a second. A sixty-tick drive of the controller is thirty million
 * instructions, so it takes about ten minutes, and the bisection that found the
 * two tasks destroying the injected input took thirty-seven such drives. Running
 * twelve at once brought that from six hours to thirty minutes, which helped, but
 * the tax being paid is interpretation of p-code inside a JVM and no amount of
 * cores removes it. SH-2 is a fixed-width sixteen-bit encoding with about sixty
 * opcodes and sixteen registers; interpreting it directly runs two to three orders
 * of magnitude faster, which turns the whole investigation from batch into
 * something interactive.
 *
 * CORRECTNESS. A subtly wrong emulator is worse than a slow one: it produces
 * confident wrong answers, which is the failure mode this project has hit
 * repeatedly. Two defences. Any opcode not implemented is reported by address and
 * encoding rather than skipped, so silence is never mistaken for success. And the
 * output format matches DensoDriveLog exactly, so the same drive can be run under
 * both and the RAM snapshots diffed - if they agree over thirty million
 * instructions, the core is right.
 *
 * SCOPE. User-mode integer core plus the single-precision FPU of the SH-2E. No
 * interrupts, no MMU, no privileged instructions: the harness enters a function
 * with a sentinel return address and runs until it comes back, exactly as the
 * Ghidra harness does.
 *
 *   sh2 <rom> <profile.csv> <out.csv> <entry[+entry...]> [maxsteps]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define ROM_SIZE   0x100000u
#define RAM_BASE   0xFFFF0000u
#define RAM_SIZE   0x10000u
#define SENTINEL   0x00FFFFF0u
#define STACK_TOP  0xFFFFBF00u

static uint8_t rom[ROM_SIZE];
static uint8_t ram[RAM_SIZE];

typedef struct {
    uint32_t r[16];
    uint32_t pc, pr, gbr, vbr, mach, macl;
    uint32_t sr;              /* only T (bit 0) and M/Q/S matter here */
    float    fr[16];
    uint32_t fpul, fpscr;
    int      delay;           /* a delayed branch is pending */
    int      halted;          /* this task hit something undecodable */
    uint32_t delay_pc;
} CPU;

static CPU cpu;

static long long unimpl_count;
static uint32_t  unimpl_pc;
static uint16_t  unimpl_op;
/* Distinct encodings, not just a total. Two million hits of one missing opcode
 * and two million of four hundred are very different problems, and the count
 * alone cannot tell them apart. */
static long long unimpl_seen[0x10000];
static uint32_t  unimpl_first_pc[0x10000];

#define T_BIT   0x00000001u
#define GET_T   (cpu.sr & T_BIT)
#define SET_T(x) (cpu.sr = (x) ? (cpu.sr | T_BIT) : (cpu.sr & ~T_BIT))

/* ---- memory ----------------------------------------------------------- */
/* Flat and forgiving. ROM low, RAM at 0xFFFF0000. Anything else reads zero and
 * swallows writes: the peripheral registers are not modelled, and a read of an
 * unmapped address returning zero is what the Ghidra harness effectively did too
 * (FINDINGS 56c). Where that matters it matters in both, so the differential
 * check still holds. */

static inline uint32_t rd8(uint32_t a) {
    if (a < ROM_SIZE) return rom[a];
    if (a - RAM_BASE < RAM_SIZE) return ram[a - RAM_BASE];
    return 0;
}
static inline uint32_t rd16(uint32_t a) {
    if (a < ROM_SIZE - 1) return ((uint32_t)rom[a] << 8) | rom[a + 1];
    if (a - RAM_BASE < RAM_SIZE - 1) {
        uint32_t o = a - RAM_BASE;
        return ((uint32_t)ram[o] << 8) | ram[o + 1];
    }
    return 0;
}
static inline uint32_t rd32(uint32_t a) {
    return (rd16(a) << 16) | rd16(a + 2);
}
/* SH2_WATCH=<hex address> reports every write to it with the instruction that
 * did it. Guessing at which of four hundred tasks wrote a byte is hopeless; this
 * answers it in one run. */
static uint32_t watch_addr;
static uint32_t watch_pc;
/* SH2_WRITESET=<file> records every distinct address the firmware writes.
 * Needed because the tick-to-tick diff cannot see a routine that writes the same
 * value every time - which is exactly what a RAM self test does, and why one ran
 * unnoticed on every tick of every drive. */
static uint8_t  wrote[RAM_SIZE];
static int      track_writes;

static inline void wr8(uint32_t a, uint32_t v) {
    if (a - RAM_BASE < RAM_SIZE) {
        if (a == watch_addr)
            fprintf(stderr, "WRITE %08X = %02X  by pc %08X\n",
                    a, (uint8_t)v, watch_pc);
        if (track_writes) wrote[a - RAM_BASE] = 1;
        ram[a - RAM_BASE] = (uint8_t)v;
    }
}
static inline void wr16(uint32_t a, uint32_t v) {
    wr8(a, v >> 8); wr8(a + 1, v & 0xFF);
}
static inline void wr32(uint32_t a, uint32_t v) {
    wr16(a, v >> 16); wr16(a + 2, v & 0xFFFF);
}

/* ---- execution -------------------------------------------------------- */

static void branch(uint32_t target) { cpu.delay = 1; cpu.delay_pc = target; }

static void step_one(void) {
    uint32_t pc = cpu.pc;
    watch_pc = pc;
    uint16_t op = (uint16_t)rd16(pc);
    uint32_t next = pc + 2;
    int was_delay = cpu.delay;
    uint32_t dpc = cpu.delay_pc;
    cpu.delay = 0;

    uint32_t n = (op >> 8) & 0xF, m = (op >> 4) & 0xF, d = op & 0xFF, d4 = op & 0xF;
    uint32_t *R = cpu.r;

    switch (op >> 12) {
    case 0x0:
        switch (op & 0xF) {
        case 0x4: wr8(R[n] + R[0], R[m]); break;                 /* mov.b Rm,@(R0,Rn) */
        case 0x5: wr16(R[n] + R[0], R[m]); break;
        case 0x6: wr32(R[n] + R[0], R[m]); break;
        case 0x7: cpu.macl = R[n] * R[m]; break;                 /* mul.l */
        case 0xC: R[n] = (int32_t)(int8_t)rd8(R[m] + R[0]); break;
        case 0xD: R[n] = (int32_t)(int16_t)rd16(R[m] + R[0]); break;
        case 0xE: R[n] = rd32(R[m] + R[0]); break;
        case 0x8:
            if (op == 0x0008) { cpu.sr &= ~T_BIT; }              /* clrt */
            else if (op == 0x0018) { cpu.sr |= T_BIT; }          /* sett */
            else if (op == 0x0028) { cpu.mach = cpu.macl = 0; }  /* clrmac */
            else goto unimplemented;
            break;
        case 0x9:
            if (op == 0x0009) { }                                /* nop */
            else if (op == 0x0019) { cpu.sr &= ~0x301u; }        /* div0u: clears M, Q, T */
            else if ((op & 0xF0FF) == 0x0029) R[n] = GET_T;       /* movt */
            else goto unimplemented;
            break;
        case 0xA:
            if      ((op & 0xF0FF) == 0x000A) R[n] = cpu.mach;
            else if ((op & 0xF0FF) == 0x001A) R[n] = cpu.macl;
            else if ((op & 0xF0FF) == 0x002A) R[n] = cpu.pr;
            else if ((op & 0xF0FF) == 0x005A) R[n] = cpu.fpul;
            else if ((op & 0xF0FF) == 0x006A) R[n] = cpu.fpscr;
            else goto unimplemented;
            break;
        case 0xB:
            if (op == 0x000B) { branch(cpu.pr); }                 /* rts */
            else if (op == 0x002B) { branch(cpu.vbr); }           /* rte, approximated */
            else goto unimplemented;
            break;
        case 0x2:
            if      ((op & 0xF0FF) == 0x0002) R[n] = cpu.sr;
            else if ((op & 0xF0FF) == 0x0012) R[n] = cpu.gbr;
            else if ((op & 0xF0FF) == 0x0022) R[n] = cpu.vbr;
            else goto unimplemented;
            break;
        case 0x3:
            /* braf Rn is PC + 4 + Rn, not Rn. Branching to the register absolutely
             * sent every switch statement in the firmware to a garbage address:
             * the compiler emits mov.w @(r0,r2),r0 to fetch a 16-bit offset from a
             * jump table and then braf r0, so the value in the register is a small
             * displacement - 0x2E here - and jumping to it lands in the interrupt
             * vector table. That is where the "executing data" of section 67b came
             * from, and it was a bug in this core rather than a harness artefact. */
            if ((op & 0xF0FF) == 0x0023) { branch(pc + 4 + R[n]); }   /* braf */
            else if ((op & 0xF0FF) == 0x0003) { cpu.pr = pc + 4; branch(pc + 4 + R[n]); }
            else goto unimplemented;
            break;
        case 0xF: {                                              /* mac.l */
            int64_t a = (int32_t)rd32(R[m]); R[m] += 4;
            int64_t b = (int32_t)rd32(R[n]); R[n] += 4;
            int64_t acc = ((int64_t)cpu.mach << 32) | cpu.macl;
            acc += a * b;
            cpu.mach = (uint32_t)(acc >> 32); cpu.macl = (uint32_t)acc;
            break; }
        default: goto unimplemented;
        }
        break;

    case 0x1: wr32(R[n] + (d4 << 2), R[m]); break;                /* mov.l Rm,@(disp,Rn) */

    case 0x2:
        switch (op & 0xF) {
        case 0x0: wr8(R[n], R[m]); break;
        case 0x1: wr16(R[n], R[m]); break;
        case 0x2: wr32(R[n], R[m]); break;
        case 0x4: R[n] -= 1; wr8(R[n], R[m]); break;
        case 0x5: R[n] -= 2; wr16(R[n], R[m]); break;
        case 0x6: R[n] -= 4; wr32(R[n], R[m]); break;
        case 0x7: {                                              /* div0s */
            uint32_t q = (R[n] >> 31) & 1, mm = (R[m] >> 31) & 1;
            cpu.sr = (cpu.sr & ~0x300u) | (q << 8) | (mm << 9);
            SET_T(q != mm); break; }
        case 0x3: goto unimplemented;   /* not an SH-2 encoding in this slot */
        case 0x8: SET_T((R[n] & R[m]) == 0); break;              /* tst */
        case 0x9: R[n] &= R[m]; break;
        case 0xA: R[n] ^= R[m]; break;
        case 0xB: R[n] |= R[m]; break;
        case 0xC: {                                              /* cmp/str */
            uint32_t t = R[n] ^ R[m];
            SET_T(!(t & 0xFF000000) || !(t & 0xFF0000) || !(t & 0xFF00) || !(t & 0xFF));
            break; }
        /* xtrct Rm,Rn takes the low half of Rm and the high half of Rn and joins
         * them: Rn = (Rm << 16) | (Rn >> 16). The version this replaces kept the
         * high half of Rn in place instead of shifting it down, which is not the
         * instruction at all. It appears in 64-bit shifts and byte-order work, so
         * getting it wrong corrupts values without disturbing control flow. */
        case 0xD: R[n] = ((R[m] & 0xFFFF) << 16) | ((R[n] >> 16) & 0xFFFF); break;
        case 0xE: cpu.macl = (uint32_t)((uint16_t)R[n] * (uint16_t)R[m]); break;
        case 0xF: cpu.macl = (uint32_t)((int32_t)(int16_t)R[n] * (int32_t)(int16_t)R[m]); break;
        default: goto unimplemented;
        }
        break;

    case 0x3:
        switch (op & 0xF) {
        case 0x0: SET_T(R[n] == R[m]); break;
        case 0x2: SET_T(R[n] >= R[m]); break;                    /* cmp/hs */
        case 0x3: SET_T((int32_t)R[n] >= (int32_t)R[m]); break;  /* cmp/ge */
        case 0x6: SET_T(R[n] > R[m]); break;                     /* cmp/hi */
        case 0x7: SET_T((int32_t)R[n] > (int32_t)R[m]); break;   /* cmp/gt */
        case 0x8: R[n] -= R[m]; break;
        case 0xC: R[n] += R[m]; break;
        /* div1, in full. The simplified version this replaces was the single
         * biggest source of divergence from the reference: the compiler emits a
         * div0s/div1 chain for every division, so getting the M and Q bookkeeping
         * wrong corrupts arithmetic across the image while control flow mostly
         * survives - which shows up as a scatter of wrong values rather than a
         * crash, and is therefore easy to mistake for a working emulator. */
        case 0x4: {
            uint32_t old_q = (cpu.sr >> 8) & 1;
            uint32_t mbit  = (cpu.sr >> 9) & 1;
            uint32_t q     = (R[n] >> 31) & 1;
            uint32_t tmp2  = R[m];
            uint32_t tmp0, tmp1;

            R[n] = (R[n] << 1) | GET_T;

            if (old_q == 0) {
                if (mbit == 0) {
                    tmp0 = R[n]; R[n] -= tmp2; tmp1 = (R[n] > tmp0);
                    q = q ? (tmp1 == 0) : tmp1;
                } else {
                    tmp0 = R[n]; R[n] += tmp2; tmp1 = (R[n] < tmp0);
                    q = q ? tmp1 : (tmp1 == 0);
                }
            } else {
                if (mbit == 0) {
                    tmp0 = R[n]; R[n] += tmp2; tmp1 = (R[n] < tmp0);
                    q = q ? tmp1 : (tmp1 == 0);
                } else {
                    tmp0 = R[n]; R[n] -= tmp2; tmp1 = (R[n] > tmp0);
                    q = q ? (tmp1 == 0) : tmp1;
                }
            }
            cpu.sr = (cpu.sr & ~0x100u) | (q << 8);
            SET_T(q == mbit);
            break; }
        case 0x5: {                                              /* dmulu.l */
            uint64_t p = (uint64_t)R[n] * (uint64_t)R[m];
            cpu.mach = (uint32_t)(p >> 32); cpu.macl = (uint32_t)p; break; }
        case 0xD: {                                              /* dmuls.l */
            int64_t p = (int64_t)(int32_t)R[n] * (int64_t)(int32_t)R[m];
            cpu.mach = (uint32_t)((uint64_t)p >> 32); cpu.macl = (uint32_t)p; break; }
        case 0xA: {                                              /* subc */
            uint32_t t = R[n] - R[m] - GET_T;
            SET_T(R[n] < R[m] + GET_T); R[n] = t; break; }
        case 0xE: {                                              /* addc */
            uint64_t t = (uint64_t)R[n] + R[m] + GET_T;
            SET_T(t >> 32); R[n] = (uint32_t)t; break; }
        case 0xB: {                                              /* subv */
            int64_t t = (int64_t)(int32_t)R[n] - (int32_t)R[m];
            SET_T(t < -2147483648LL || t > 2147483647LL); R[n] = (uint32_t)t; break; }
        case 0xF: {                                              /* addv */
            int64_t t = (int64_t)(int32_t)R[n] + (int32_t)R[m];
            SET_T(t < -2147483648LL || t > 2147483647LL); R[n] = (uint32_t)t; break; }
        default: goto unimplemented;
        }
        break;

    case 0x4:
        switch (op & 0xFF) {
        case 0x00: SET_T((R[n] >> 31) & 1); R[n] <<= 1; break;   /* shll */
        case 0x01: SET_T(R[n] & 1); R[n] >>= 1; break;           /* shlr */
        case 0x04: { uint32_t t = (R[n] >> 31) & 1;              /* rotl */
                     R[n] = (R[n] << 1) | t; SET_T(t); break; }
        case 0x05: { uint32_t t = R[n] & 1;                      /* rotr */
                     R[n] = (R[n] >> 1) | (t << 31); SET_T(t); break; }
        case 0x08: R[n] <<= 2; break;
        case 0x09: R[n] >>= 2; break;
        case 0x18: R[n] <<= 8; break;
        case 0x19: R[n] >>= 8; break;
        case 0x28: R[n] <<= 16; break;
        case 0x29: R[n] >>= 16; break;
        case 0x20: SET_T((R[n] >> 31) & 1); R[n] = (uint32_t)((int32_t)R[n] << 1); break;
        case 0x21: SET_T(R[n] & 1); R[n] = (uint32_t)((int32_t)R[n] >> 1); break;
        case 0x10: R[n] -= 1; SET_T(R[n] == 0); break;           /* dt */
        case 0x11: SET_T((int32_t)R[n] >= 0); break;             /* cmp/pz */
        case 0x15: SET_T((int32_t)R[n] > 0); break;              /* cmp/pl */
        case 0x0B: cpu.pr = pc + 4; branch(R[n]); break;         /* jsr */
        case 0x2B: branch(R[n]); break;                          /* jmp */
        case 0x0E: cpu.sr = R[n]; break;                         /* ldc SR */
        case 0x1E: cpu.gbr = R[n]; break;
        case 0x2E: cpu.vbr = R[n]; break;
        case 0x0A: cpu.mach = R[n]; break;
        case 0x1A: cpu.macl = R[n]; break;
        case 0x2A: cpu.pr = R[n]; break;
        case 0x5A: cpu.fpul = R[n]; break;
        case 0x22: wr32(R[n] -= 4, cpu.pr); break;               /* sts.l pr,@-Rn */
        case 0x02: wr32(R[n] -= 4, cpu.mach); break;
        case 0x12: wr32(R[n] -= 4, cpu.macl); break;
        case 0x26: cpu.pr = rd32(R[n]); R[n] += 4; break;        /* lds.l @Rn+,pr */
        case 0x06: cpu.mach = rd32(R[n]); R[n] += 4; break;
        case 0x16: cpu.macl = rd32(R[n]); R[n] += 4; break;
        case 0x07: cpu.sr = rd32(R[n]); R[n] += 4; break;
        case 0x17: cpu.gbr = rd32(R[n]); R[n] += 4; break;
        case 0x27: cpu.vbr = rd32(R[n]); R[n] += 4; break;
        case 0x03: wr32(R[n] -= 4, cpu.sr); break;
        case 0x13: wr32(R[n] -= 4, cpu.gbr); break;
        case 0x23: wr32(R[n] -= 4, cpu.vbr); break;
        case 0x1B: { uint32_t v = rd8(R[n]); SET_T(v == 0);      /* tas.b */
                     wr8(R[n], v | 0x80); break; }
        /* Rotate through carry. This one instruction was 90 percent of the
         * unimplemented hits: the compiler uses it for every multi-word shift,
         * so leaving it out corrupts arithmetic all over the image while the
         * emulator still appears to run. */
        case 0x24: { uint32_t t = (R[n] >> 31) & 1;             /* rotcl */
                     R[n] = (R[n] << 1) | GET_T; SET_T(t); break; }
        case 0x25: { uint32_t t = R[n] & 1;                     /* rotcr */
                     R[n] = (R[n] >> 1) | (GET_T << 31); SET_T(t); break; }
        /* FPU system registers. Saved and restored in the prologue of any
         * function that touches floating point. */
        case 0x52: wr32(R[n] -= 4, cpu.fpul); break;            /* sts.l FPUL,@-Rn */
        case 0x62: wr32(R[n] -= 4, cpu.fpscr); break;           /* sts.l FPSCR,@-Rn */
        case 0x56: cpu.fpul = rd32(R[n]); R[n] += 4; break;     /* lds.l @Rn+,FPUL */
        case 0x66: cpu.fpscr = rd32(R[n]); R[n] += 4; break;    /* lds.l @Rn+,FPSCR */
        case 0x6A: cpu.fpscr = R[n]; break;                     /* lds Rm,FPSCR */
        case 0x0C: case 0x1C: case 0x2C: goto unimplemented;     /* shad/shld family */
        case 0x0F: {                                             /* mac.w */
            int32_t a = (int16_t)rd16(R[m]); R[m] += 2;
            int32_t b = (int16_t)rd16(R[n]); R[n] += 2;
            int64_t acc = ((int64_t)cpu.mach << 32) | cpu.macl;
            acc += (int64_t)a * b;
            cpu.mach = (uint32_t)(acc >> 32); cpu.macl = (uint32_t)acc; break; }
        default: goto unimplemented;
        }
        break;

    case 0x5: R[n] = rd32(R[m] + (d4 << 2)); break;              /* mov.l @(disp,Rm),Rn */

    case 0x6:
        switch (op & 0xF) {
        case 0x0: R[n] = (int32_t)(int8_t)rd8(R[m]); break;
        case 0x1: R[n] = (int32_t)(int16_t)rd16(R[m]); break;
        case 0x2: R[n] = rd32(R[m]); break;
        case 0x3: R[n] = R[m]; break;
        case 0x4: R[n] = (int32_t)(int8_t)rd8(R[m]); R[m] += 1; break;
        case 0x5: R[n] = (int32_t)(int16_t)rd16(R[m]); R[m] += 2; break;
        case 0x6: R[n] = rd32(R[m]); R[m] += 4; break;
        case 0x7: R[n] = ~R[m]; break;
        case 0x8: R[n] = ((R[m] & 0xFF) << 8) | ((R[m] >> 8) & 0xFF) | (R[m] & 0xFFFF0000); break;
        case 0x9: R[n] = (R[m] >> 16) | (R[m] << 16); break;
        case 0xA: { uint64_t t = 0 - (uint64_t)R[m] - GET_T;     /* negc */
                    SET_T(t >> 32); R[n] = (uint32_t)t; break; }
        case 0xB: R[n] = (uint32_t)(-(int32_t)R[m]); break;
        case 0xC: R[n] = R[m] & 0xFF; break;
        case 0xD: R[n] = R[m] & 0xFFFF; break;
        case 0xE: R[n] = (int32_t)(int8_t)R[m]; break;
        case 0xF: R[n] = (int32_t)(int16_t)R[m]; break;
        default: goto unimplemented;
        }
        break;

    case 0x7: R[n] += (int32_t)(int8_t)d; break;                 /* add #imm,Rn */

    case 0x8:
        switch ((op >> 8) & 0xF) {
        case 0x0: wr8(R[m] + d4, R[0]); break;
        case 0x1: wr16(R[m] + (d4 << 1), R[0]); break;
        case 0x4: R[0] = (int32_t)(int8_t)rd8(R[m] + d4); break;
        case 0x5: R[0] = (int32_t)(int16_t)rd16(R[m] + (d4 << 1)); break;
        case 0x8: SET_T(R[0] == (uint32_t)(int32_t)(int8_t)d); break;
        case 0x9: if (GET_T)  { branch(pc + 4 + ((int32_t)(int8_t)d << 1)); cpu.delay = 0;
                                next = pc + 4 + ((int32_t)(int8_t)d << 1); } break;  /* bt */
        case 0xB: if (!GET_T) { next = pc + 4 + ((int32_t)(int8_t)d << 1); } break;  /* bf */
        case 0xD: if (GET_T)  branch(pc + 4 + ((int32_t)(int8_t)d << 1)); break;     /* bt/s */
        case 0xF: if (!GET_T) branch(pc + 4 + ((int32_t)(int8_t)d << 1)); break;     /* bf/s */
        default: goto unimplemented;
        }
        break;

    /* mov.w @(disp,PC),Rn - SIGN EXTENDED. Getting this wrong turns the negative
     * stack adjustment that opens most functions into a large positive one, so
     * r15 walks out of RAM and every local access afterwards reads zero. It is
     * the same sign-extension that FINDINGS 45 turned on: a 16-bit literal is how
     * this architecture names a 0xFFFF.... address in the first place. */
    case 0x9: R[n] = (uint32_t)(int32_t)(int16_t)rd16(pc + 4 + (d << 1)); break;

    case 0xA: { int32_t disp = (op & 0x800) ? (int32_t)(op | 0xFFFFF000) : (op & 0xFFF);
                branch(pc + 4 + (disp << 1)); break; }           /* bra */
    case 0xB: { int32_t disp = (op & 0x800) ? (int32_t)(op | 0xFFFFF000) : (op & 0xFFF);
                cpu.pr = pc + 4; branch(pc + 4 + (disp << 1)); break; }  /* bsr */

    case 0xC:
        switch ((op >> 8) & 0xF) {
        case 0x0: wr8(cpu.gbr + d, R[0]); break;
        case 0x1: wr16(cpu.gbr + (d << 1), R[0]); break;
        case 0x2: wr32(cpu.gbr + (d << 2), R[0]); break;
        case 0x4: R[0] = (int32_t)(int8_t)rd8(cpu.gbr + d); break;
        case 0x5: R[0] = (int32_t)(int16_t)rd16(cpu.gbr + (d << 1)); break;
        case 0x6: R[0] = rd32(cpu.gbr + (d << 2)); break;
        case 0x7: R[0] = (pc + 4 & ~3u) + (d << 2); break;       /* mova */
        case 0x8: SET_T((R[0] & d) == 0); break;
        case 0x9: R[0] &= d; break;
        case 0xA: R[0] ^= d; break;
        case 0xB: R[0] |= d; break;
        case 0xC: SET_T((rd8(cpu.gbr + R[0]) & d) == 0); break;
        case 0xD: wr8(cpu.gbr + R[0], rd8(cpu.gbr + R[0]) & d); break;
        case 0xE: wr8(cpu.gbr + R[0], rd8(cpu.gbr + R[0]) ^ d); break;
        case 0xF: wr8(cpu.gbr + R[0], rd8(cpu.gbr + R[0]) | d); break;
        default: goto unimplemented;
        }
        break;

    case 0xD: R[n] = rd32((pc + 4 & ~3u) + (d << 2)); break;     /* mov.l @(disp,PC),Rn */
    case 0xE: R[n] = (uint32_t)(int32_t)(int8_t)d; break;        /* mov #imm,Rn */

    case 0xF: {
        /* SH-2E single-precision FPU. Enough of it for the control code; anything
         * missing is reported rather than ignored. */
        float *F = cpu.fr;
        switch (op & 0xF) {
        case 0x0: F[n] = F[n] + F[m]; break;
        case 0x1: F[n] = F[n] - F[m]; break;
        case 0x2: F[n] = F[n] * F[m]; break;
        case 0x3: F[n] = F[n] / F[m]; break;
        case 0x4: SET_T(F[n] == F[m]); break;
        case 0x5: SET_T(F[n] > F[m]); break;
        case 0x6: { uint32_t v = rd32(R[m] + R[0]); memcpy(&F[n], &v, 4); break; }
        case 0x7: { uint32_t v; memcpy(&v, &F[m], 4); wr32(R[n] + R[0], v); break; }
        case 0x8: { uint32_t v = rd32(R[m]); memcpy(&F[n], &v, 4); break; }
        case 0x9: { uint32_t v = rd32(R[m]); memcpy(&F[n], &v, 4); R[m] += 4; break; }
        case 0xA: { uint32_t v; memcpy(&v, &F[m], 4); wr32(R[n], v); break; }
        case 0xB: { uint32_t v; memcpy(&v, &F[m], 4); wr32(R[n] -= 4, v); break; }
        case 0xC: F[n] = F[m]; break;
        case 0xE: { /* fmac */ F[n] = F[0] * F[m] + F[n]; break; }
        case 0xD:
            /* The 0xFn_D group, straight from the SH-2E encoding. Getting this
             * mapping shifted by one is not a subtle failure - FLDI0 silently
             * doing nothing leaves a stale value in the register and the next
             * comparison branches the wrong way, which ended the drive after a
             * hundred instructions instead of a hundred and seventy thousand. */
            switch ((op >> 4) & 0xF) {
            case 0x0: memcpy(&F[n], &cpu.fpul, 4); break;        /* fsts FPUL,FRn */
            case 0x1: memcpy(&cpu.fpul, &F[n], 4); break;        /* flds FRn,FPUL */
            case 0x2: F[n] = (float)(int32_t)cpu.fpul; break;    /* float FPUL,FRn */
            case 0x3: { int32_t v = (int32_t)F[n];               /* ftrc FRn,FPUL */
                        memcpy(&cpu.fpul, &v, 4); break; }
            case 0x4: F[n] = -F[n]; break;                       /* fneg */
            case 0x5: F[n] = F[n] < 0 ? -F[n] : F[n]; break;     /* fabs */
            case 0x6: { float x = F[n]; float g = x > 0 ? x : 0;  /* fsqrt */
                        if (g > 0) { for (int i = 0; i < 24; i++) g = 0.5f * (g + x / g); }
                        F[n] = g; break; }
            case 0x8: F[n] = 0.0f; break;                        /* fldi0 */
            case 0x9: F[n] = 1.0f; break;                        /* fldi1 */
            default: goto unimplemented;
            }
            break;
        default: goto unimplemented;
        }
        break; }

    default: goto unimplemented;
    }

    cpu.pc = was_delay ? dpc : next;
    return;

unimplemented:
    /* Never silently, and never onward. An emulator that skips what it does not
     * know produces a plausible wrong answer, which costs far more than stopping.
     *
     * Stopping is also what the reference does, and that turned out to be the
     * whole difference. Ghidra's EmulatorHelper.step returns false when an
     * instruction will not decode, and DensoDriveLog breaks out of that task. This
     * core counted the miss and carried on, so once a task entered with zeroed
     * registers computed a null jump into the vector table, the two emulators
     * executed different garbage from there and their RAM diverged. Matching the
     * reference means halting the task, not the drive. */
    cpu.halted = 1;
    if (!unimpl_count) { unimpl_pc = pc; unimpl_op = op; }
    unimpl_count++;
    if (!unimpl_seen[op]) unimpl_first_pc[op] = pc;
    unimpl_seen[op]++;
    cpu.pc = was_delay ? dpc : next;
}

/* ---- harness ---------------------------------------------------------- */

static long long trace_left;   /* SH2_TRACE=N prints the first N instructions */
static uint32_t  trace_from;   /* SH2_TRACE_FROM=pc arms the trace at that pc */
static int       trace_armed;

static long long run_entry(uint32_t entry, long long maxsteps) {
    cpu.pc = entry;
    cpu.r[15] = STACK_TOP;
    cpu.pr = SENTINEL;
    cpu.delay = 0;
    cpu.halted = 0;
    long long steps = 0;
    while (steps < maxsteps) {
        uint32_t pc = cpu.pc;
        if (pc == SENTINEL || pc == 0 || pc >= ROM_SIZE) break;
        if (cpu.halted) break;
        if (trace_from && pc == trace_from) trace_armed = 1;
        if (trace_left > 0 && (!trace_from || trace_armed)) {
            fprintf(stderr, "%08X %04X  r0=%08X r1=%08X r2=%08X r4=%08X r15=%08X T=%u\n",
                    pc, (uint16_t)rd16(pc), cpu.r[0], cpu.r[2], cpu.r[6],
                    cpu.r[4], cpu.r[15], (unsigned)GET_T);
            trace_left--;
        }
        step_one();
        steps++;
    }
    return steps;
}

#define MAX_ENTRIES 1024
#define MAX_TICKS   4096

int main(int argc, char **argv) {
    if (argc < 5) {
        fprintf(stderr,
            "usage: %s <rom> <profile.csv> <out.csv> <entry[+entry...]> [maxsteps]\n",
            argv[0]);
        return 2;
    }
    long long maxsteps = argc > 5 ? atoll(argv[5]) : 200000;
    { const char *t = getenv("SH2_TRACE"); if (t) trace_left = atoll(t); }
    { const char *w = getenv("SH2_WATCH"); if (w) watch_addr = (uint32_t)strtoul(w, 0, 16); }
    { const char *f = getenv("SH2_TRACE_FROM"); if (f) trace_from = (uint32_t)strtoul(f, 0, 16); }
    const char *wsfile = getenv("SH2_WRITESET");
    if (wsfile) track_writes = 1;

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fread(rom, 1, ROM_SIZE, f);
    fclose(f);

    /* The entry list can be a file. Four hundred tasks is about 4,400 characters
     * and passing that as one argument through wsl silently failed - the process
     * did not start and nothing was written, which looked like every input driving
     * nothing rather than like an error. */
    static char entrybuf[1 << 16];
    char *entryspec = argv[4];
    if (entryspec[0] == '@') {
        FILE *ef = fopen(entryspec + 1, "r");
        if (!ef) { perror(entryspec + 1); return 1; }
        size_t got = fread(entrybuf, 1, sizeof entrybuf - 1, ef);
        fclose(ef);
        entrybuf[got] = 0;
        for (char *q = entrybuf; *q; q++) if (*q == '\n' || *q == '\r') *q = 0;
        entryspec = entrybuf;
    }

    static uint32_t entries[MAX_ENTRIES];
    int nentries = 0;
    for (char *p = entryspec; *p && nentries < MAX_ENTRIES; ) {
        entries[nentries++] = (uint32_t)strtoul(p, &p, 16);
        while (*p == '+' || *p == 'x' || *p == '0') { if (*p == '+') { p++; break; } p++; }
    }

    FILE *pf = fopen(argv[2], "r");
    if (!pf) { perror(argv[2]); return 1; }
    FILE *of = fopen(argv[3], "w");
    if (!of) { perror(argv[3]); return 1; }

    static uint8_t prev[RAM_SIZE];
    static uint8_t seen[RAM_SIZE];
    static uint8_t cur[RAM_SIZE];
    static uint8_t *ticks[MAX_TICKS];
    int nticks = 0, first = 1;
    long long total = 0;

    char line[1 << 16];
    while (fgets(line, sizeof line, pf) && nticks < MAX_TICKS) {
        if (line[0] == '#' || line[0] == '\n') continue;
        /* tick,addr:size=value,... */
        char *p = strchr(line, ',');
        while (p) {
            uint32_t addr = (uint32_t)strtoul(p + 1, &p, 16);
            int size = 1;
            if (*p == ':') size = (int)strtol(p + 1, &p, 10);
            if (*p == '=') {
                uint32_t v = (uint32_t)strtoul(p + 1, &p, 0);
                for (int i = 0; i < size; i++)
                    wr8(addr + i, (v >> (8 * (size - 1 - i))) & 0xFF);
            }
            p = strchr(p, ',');
        }
        for (int i = 0; i < nentries; i++) total += run_entry(entries[i], maxsteps);

        memcpy(cur, ram, RAM_SIZE);
        uint8_t *snap = malloc(RAM_SIZE);
        memcpy(snap, cur, RAM_SIZE);
        ticks[nticks++] = snap;
        if (!first) {
            for (uint32_t i = 0; i < RAM_SIZE; i++)
                if (cur[i] != prev[i]) seen[i] = 1;
        }
        memcpy(prev, cur, RAM_SIZE);
        first = 0;
    }

    fprintf(of, "tick");
    for (uint32_t i = 0; i < RAM_SIZE; i++)
        if (seen[i]) fprintf(of, ",%08X", RAM_BASE + i);
    fprintf(of, "\n");
    for (int t = 0; t < nticks; t++) {
        fprintf(of, "%d", t);
        for (uint32_t i = 0; i < RAM_SIZE; i++)
            if (seen[i]) fprintf(of, ",%u", ticks[t][i]);
        fprintf(of, "\n");
    }
    fclose(of);
    fclose(pf);

    if (wsfile) {
        FILE *wf = fopen(wsfile, "w");
        if (wf) {
            int n = 0;
            for (uint32_t i = 0; i < RAM_SIZE; i++) if (wrote[i]) n++;
            fprintf(wf, "%d\n", n);
            for (uint32_t i = 0; i < RAM_SIZE; i++)
                if (wrote[i]) fprintf(wf, "%08X\n", RAM_BASE + i);
            fclose(wf);
        }
    }

    int changed = 0;
    for (uint32_t i = 0; i < RAM_SIZE; i++) changed += seen[i];
    printf("RESULT ticks=%d instructions=%lld changed=%d failed=0 -> %s\n",
           nticks, total, changed, argv[3]);
    if (unimpl_count) {
        int distinct = 0;
        for (int i = 0; i < 0x10000; i++) if (unimpl_seen[i]) distinct++;
        printf("UNIMPLEMENTED %lld hits across %d distinct encodings,"
               " first at %08X op=%04X\n",
               unimpl_count, distinct, unimpl_pc, unimpl_op);
        printf("  op    hits\n");
        for (int pass = 0; pass < 24; pass++) {
            int best = -1; long long bn = 0;
            for (int i = 0; i < 0x10000; i++)
                if (unimpl_seen[i] > bn) { bn = unimpl_seen[i]; best = i; }
            if (best < 0) break;
            printf("  %04X  %-8lld first at %08X\n", best, bn, unimpl_first_pc[best]);
            unimpl_seen[best] = 0;
        }
    }
    return 0;
}
