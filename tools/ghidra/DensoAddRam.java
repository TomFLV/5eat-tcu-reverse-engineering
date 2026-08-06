// Give a Denso image its on-chip RAM block.
//
// These images are imported as a flat binary at 0, so the program contains the ROM
// and nothing else. The SH7058 has 48 KB of on-chip RAM high in the address space,
// and without a block there:
//
//   * Ghidra creates no symbols for RAM addresses, so the decompiled C never
//     mentions them and a search of it concludes, wrongly, that the code does not
//     touch them. That is the whole of FINDINGS section 45 and 46.
//   * The emulator has nowhere to put variables. A function reading pedal position
//     reads unmapped memory, so every run produces the same answer no matter what
//     inputs are set, which is exactly what section 49's first sweep showed.
//
// Addresses come from the SH7058 hardware manual: on-chip RAM occupies the top of
// the address space, and every RAM address this project has resolved out of literal
// pools lands inside 0xFFFF0000-0xFFFFFFFF.
//
//@category 5EAT

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

public class DensoAddRam extends GhidraScript {

    private static final long RAM_BASE = 0xFFFF0000L;
    private static final long RAM_SIZE = 0x00010000L;

    @Override
    public void run() throws Exception {
        Memory mem = currentProgram.getMemory();
        Address base = toAddr(RAM_BASE);

        for (MemoryBlock b : mem.getBlocks()) {
            if (b.getStart().getOffset() == RAM_BASE) {
                println("RESULT already present: " + b.getName());
                return;
            }
        }

        MemoryBlock ram = mem.createInitializedBlock(
                "onchip_ram", base, RAM_SIZE, (byte) 0, monitor, false);
        ram.setRead(true);
        ram.setWrite(true);
        ram.setExecute(false);
        ram.setComment("SH7058 on-chip RAM. Added by DensoAddRam so RAM references "
                     + "resolve and the emulator has somewhere to keep variables.");

        println(String.format("RESULT added %s %s-%s", ram.getName(),
                ram.getStart(), ram.getEnd()));
    }
}
