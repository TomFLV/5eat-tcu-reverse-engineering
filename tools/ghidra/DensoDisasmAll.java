// Export the full disassembly of an image: every instruction and every data item,
// in address order, with raw bytes and resolved operands.
//
// WHY THIS EXISTS. This project had only decompiler output - pseudocode C - and drew
// conclusions about the instruction stream from it. That does not work. The
// decompiler deliberately discards the things reverse engineering a ROM depends on:
// literal pools vanish, PC-relative loads appear as bare symbol names, and an
// unreferenced constant gets no symbol at all so it is simply invisible.
//
// A concrete case: the Select Monitor staging buffer addresses sit in literal pools
// at 0x7FCAE, 0x7FCC2, 0x80032 and 0x80742. Ghidra created no symbols there, so
// nothing in the decompiled C mentions them and a search of that C concluded, wrongly,
// that the addresses were unreachable.
//
// Output is one line per address:
//
//   0009BE0  00 08 68 70                          .data  0x00086870
//   00099E0  81 C0                                .word  0x81C0        ; -> 0xFFFF81C0
//   0004A2C  D1 27        mov.l    @(0x9c,pc),r1  ; = 0x00086870
//
// A .word whose sign-extended value lands in RAM is annotated, because that is how
// SH-2 holds a RAM address: it cannot load a 32-bit constant in one instruction, so
// the address is a 16-bit literal that mov.w sign-extends.
//
//@category 5EAT

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSetView;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;

import java.io.*;

public class DensoDisasmAll extends GhidraScript {

    private static final long RAM_LO = 0xFFFF0000L;
    private static final long RAM_HI = 0xFFFFFFFEL;

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        String out = a.length > 0 ? a[0] : System.getProperty("disasm.out", "disasm.txt");

        Listing listing = currentProgram.getListing();
        PrintWriter w = new PrintWriter(new BufferedWriter(new FileWriter(out), 1 << 20));

        w.println("; full disassembly of " + currentProgram.getName());
        w.println("; language " + currentProgram.getLanguageID());
        w.println("; address  bytes                mnemonic / data");
        w.println();

        long insns = 0, data = 0, ramRefs = 0;

        CodeUnitIterator it = listing.getCodeUnits(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) {
                break;
            }
            CodeUnit cu = it.next();
            Address addr = cu.getMinAddress();

            StringBuilder b = new StringBuilder();
            b.append(String.format("%08X  ", addr.getOffset()));

            byte[] raw;
            try {
                raw = cu.getBytes();
            } catch (Exception e) {
                raw = new byte[0];
            }
            StringBuilder hex = new StringBuilder();
            for (int i = 0; i < raw.length && i < 8; i++) {
                hex.append(String.format("%02X ", raw[i] & 0xFF));
            }
            b.append(String.format("%-26s", hex.toString()));

            if (cu instanceof Instruction) {
                insns++;
                Instruction ins = (Instruction) cu;
                b.append(ins.toString());

                // Resolve what a PC-relative load actually reads. This is the part
                // the decompiler throws away.
                for (Reference r : ins.getReferencesFrom()) {
                    Address to = r.getToAddress();
                    if (to == null || !to.isMemoryAddress()) {
                        continue;
                    }
                    Data d = listing.getDataAt(to);
                    if (d != null && d.getValue() instanceof Scalar) {
                        long v = ((Scalar) d.getValue()).getUnsignedValue();
                        b.append(String.format("   ; [%08X] = 0x%X", to.getOffset(), v));
                        long sx = sext16(v, d.getLength());
                        if (sx >= RAM_LO && sx <= RAM_HI) {
                            b.append(String.format(" -> RAM 0x%08X", sx));
                            ramRefs++;
                        }
                    }
                }
            } else {
                data++;
                Data d = (Data) cu;
                Object val = d.getValue();
                b.append(String.format("%-10s", "." + d.getDataType().getName()));
                if (val instanceof Scalar) {
                    long v = ((Scalar) val).getUnsignedValue();
                    b.append(String.format("0x%X", v));
                    long sx = sext16(v, d.getLength());
                    if (sx >= RAM_LO && sx <= RAM_HI) {
                        b.append(String.format("        ; -> RAM 0x%08X", sx));
                        ramRefs++;
                    }
                } else if (val != null) {
                    b.append(val.toString());
                }
            }
            w.println(b.toString());
        }

        w.close();
        println("RESULT instructions=" + insns + " data=" + data
                + " ramLiterals=" + ramRefs + " -> " + out);
    }

    /** A 16-bit literal is a RAM address once mov.w sign-extends it. */
    private long sext16(long v, int len) {
        if (len != 2) {
            return v & 0xFFFFFFFFL;
        }
        return ((v & 0x8000L) != 0 ? (v | 0xFFFF0000L) : v) & 0xFFFFFFFFL;
    }
}
